import copy
import json
import threading
import traceback
from time import time

import nuke  # type: ignore
import websocket

from . import run
from .cmd import get_run
from .common import execute_in_main_thread, get_settings, show_message
from .connection import GET, get_ip_from_url
from .nodes import get_input
from .queue_manager import get_project_jobs, interrupt
from .read_media import create_read, resolve_filename

active_recoveries = set()


def get_recovery_run_node(job):
    recovery_data = job["extra_data"].get("comfyui2nuke", {})
    run_node = nuke.toNode(recovery_data.get("run_node", ""))
    if run_node:
        return run_node

    prompt = job["prompt"]
    for node in nuke.allNodes(recurseGroups=True):
        if not node.knob("run"):
            continue

        run_node = get_run(node)
        output_node = get_input(run_node, 0)
        if output_node and output_node.name() in prompt:
            return run_node


def get_recovery_settings(job, run_node):
    recovery_data = job["extra_data"].get("comfyui2nuke", {})
    settings = get_settings(run_node)
    settings.update(recovery_data.get("settings", {}))
    settings["URL"] = job["url"]
    settings["project_name"] = nuke.root().name()
    settings["pre_inference_time"] = settings.get("pre_inference_time", 0)
    settings["inference_time"] = time()

    if settings.get("filename_prefix"):
        return settings

    for node_data in job["prompt"].values():
        inputs = node_data.get("inputs", {})
        for key in ("filename_prefix", "file_path"):
            if inputs.get(key):
                settings["filename_prefix"] = inputs[key]
                return settings

    return settings


def finish_recovered_job(run_node, data, settings):
    filename = resolve_filename(settings)
    if not filename:
        show_message(
            "The recovered ComfyUI job finished, but its output was not found."
        )
        return

    try:
        read = create_read(run_node, data, settings, filename)
        if not read:
            show_message(
                "The recovered ComfyUI job finished, but no Read node was created."
            )
            return

        run.remove_all_error_style(run_node)
        run.states[run_node.fullName()] = copy.deepcopy(data)
        callback = run_node.parent().knob("inferenceEnd")
        if callback:
            callback.execute()
    except Exception:
        error = traceback.format_exc()
        print(error)
        show_message(error)


def restore_job_progress(job, run_node):
    recovery_key = (job["url"], job["prompt_id"])
    if recovery_key in active_recoveries:
        return False

    active_recoveries.add(recovery_key)
    settings = get_recovery_settings(job, run_node)
    data = job["prompt"]
    progress = [nuke.ProgressTask("Inferencing")]
    progress[0].setProgress(0)
    progress[0].setMessage(
        "Restored {} job ({})".format(job["status"], get_ip_from_url(job["url"]))
    )
    finished = threading.Event()
    cancelled = [False]
    execution_error = [""]

    def close_progress():
        if progress:
            del progress[0]

    def on_message(ws, message):
        try:
            if len(message) > 1024 * 200:
                return
            message = json.loads(message)
        except Exception:
            return

        message_data = message.get("data") or {}
        prompt_id = message_data.get("prompt_id")
        if prompt_id and prompt_id != job["prompt_id"]:
            return

        message_type = message.get("type")
        if message_type == "execution_start":
            settings["inference_time"] = time()
        elif message_type == "executed":
            node_name = message_data.get("node")
            execute_in_main_thread(
                run.update_node,
                args=(node_name, message_data, run_node, settings),
            )
        elif message_type == "progress" and progress:
            maximum = float(message_data.get("max") or 0.01)
            value = int(message_data.get("value", 0) * 100 / maximum)
            progress[0].setProgress(value)
        elif message_type == "executing":
            node_name = message_data.get("node")
            if node_name and progress:
                progress[0].setProgress(0)
                progress[0].setMessage(node_name)
            elif not node_name:
                close_progress()
                finished.set()
        elif message_type == "execution_error":
            execution_error[0] = message_data.get(
                "exception_message", "ComfyUI execution failed."
            )
            close_progress()
            finished.set()

    def on_error(ws, error):
        if "connected" in str(error):
            return
        execution_error[0] = "Error restoring ComfyUI progress: {}".format(error)
        close_progress()
        finished.set()

    url = "{}/ws?clientId={}".format(job["url"].replace("http", "ws"), job["client_id"])
    ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error)

    def monitor_job():
        check_count = 0
        while not finished.wait(0.1):
            if progress and progress[0].isCancelled():
                confirm = nuke.executeInMainThreadWithResult(
                    lambda: nuke.ask(
                        "Are you sure? This will stop the ComfyUI inference"
                    )
                )
                if confirm:
                    cancelled[0] = True
                    interrupt(settings, job["client_id"])
                    close_progress()
                    finished.set()
                    break

                if progress:
                    progress[0] = nuke.ProgressTask("Inferencing")
                    progress[0].setMessage("Restored ComfyUI job")

            check_count += 1
            if check_count < 10:
                continue

            check_count = 0
            queue = GET("queue", settings, warning=False)
            if queue is None:
                continue

            queued_ids = {
                item[1]
                for key in ("queue_running", "queue_pending")
                for item in queue.get(key, [])
            }
            if job["prompt_id"] not in queued_ids:
                close_progress()
                finished.set()

        ws.close()
        active_recoveries.discard(recovery_key)

        if cancelled[0]:
            return
        if execution_error[0]:
            show_message(execution_error[0])
            return

        execute_in_main_thread(
            finish_recovered_job,
            args=(run_node, data, settings),
        )

    threading.Thread(target=ws.run_forever, daemon=True).start()
    threading.Thread(target=monitor_job, daemon=True).start()
    return True


def restore_queue_progress():
    jobs = get_project_jobs()
    if not jobs:
        show_message("No queued ComfyUI jobs match the current Nuke project.")
        return

    restored = 0
    missing_nodes = []
    for job in jobs:
        run_node = get_recovery_run_node(job)
        if not run_node:
            missing_nodes.append(job["client_id"])
            continue
        if restore_job_progress(job, run_node):
            restored += 1

    message = "Restored progress for {} ComfyUI job(s).".format(restored)
    if missing_nodes:
        message += "\n\nRun node not found for:\n{}".format("\n".join(missing_nodes))
    show_message(message)
