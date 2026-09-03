import copy
import traceback
from time import time

import nuke  # type: ignore

from . import run
from .cmd import get_run
from .common import get_settings, show_message
from .comfy_job import ComfyJob
from .connection import get_ip_from_url
from .nodes import get_input
from .queue_manager import get_project_jobs
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


class RecoveryJob(ComfyJob):
    def __init__(self, job, run_node):
        settings = get_recovery_settings(job, run_node)
        super().__init__(
            run_node,
            settings,
            run.update_node,
            client_id=job["client_id"],
            prompt_id=job["prompt_id"],
        )
        self.job = job
        self.data = job["prompt"]
        self.recovery_key = (job["url"], job["prompt_id"])

    def format_connection_error(self, error):
        return "Error restoring ComfyUI progress: {}".format(error)

    def cleanup(self):
        active_recoveries.discard(self.recovery_key)

    def finish(self):
        if self.execution_error:
            show_message(self.execution_error)
            return

        filename = resolve_filename(self.settings)
        if not filename:
            show_message(
                "The recovered ComfyUI job finished, but its output was not found."
            )
            return

        try:
            read = create_read(
                self.run_node,
                self.data,
                self.settings,
                filename,
            )
            if not read:
                show_message(
                    "The recovered ComfyUI job finished, but no Read node was "
                    "created."
                )
                return

            run.remove_all_error_style(self.run_node)
            run.states[self.run_node.fullName()] = copy.deepcopy(self.data)
            callback = self.run_node.parent().knob("inferenceEnd")
            if callback:
                callback.execute()
        except Exception:
            error = traceback.format_exc()
            print(error)
            show_message(error)

    def start(self):
        active_recoveries.add(self.recovery_key)
        message = "Restored {} job ({})".format(
            self.job["status"],
            get_ip_from_url(self.job["url"]),
        )
        self.set_progress(0, message, include_ip=False)
        self.start_monitor()
        return True


def restore_job_progress(job, run_node):
    recovery_key = (job["url"], job["prompt_id"])
    if recovery_key in active_recoveries:
        return False

    recovery = RecoveryJob(job, run_node)
    return recovery.start()


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
