# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import textwrap
import sys
import nuke  # type: ignore
import os
import traceback
from time import sleep, time
import websocket
import json
import threading
import copy

from ..nuke_util.nuke_util import (
    set_tile_color,
    get_connected_nodes,
    get_user_path,
    get_project_name,
)
from .common import (
    update_images_and_mask_inputs,
    get_settings,
    show_message,
    execute_in_main_thread,
)
from .connection import POST, get_ip_from_url
from .queue_manager import (
    resolve_submission_target,
    interrupt,
    get_prompt_id,
    show_queue,
    resolve_queue_position,
)
from .nodes import extract_data
from .read_media import (
    create_read,
    update_filename_prefix,
    exr_filepath_fixed,
    resolve_filename,
    create_empty_read,
)

states = {}
prompt_counter = 0


def error_node_style(node_name, enable, message="", run_node=None):
    if run_node:
        node = run_node.parent().node(node_name)
    else:
        node = nuke.toNode(node_name)

    if not node:
        return

    if enable:
        set_tile_color(node, [0, 1, 1])
        message = " ".join(message.split()[:30])
        formatted_message = "\n".join(textwrap.wrap(message, width=30))
        node.knob("label").setValue("ERROR:\n" + formatted_message)
    else:
        node["tile_color"].setValue(0)
        node.knob("label").setValue("")


def remove_all_error_style(root_node):
    for n in get_connected_nodes(root_node):
        label_knob = n.knob("label")
        if "ERROR" in label_knob.value():
            error_node_style(n.fullName(), False)


def update_node(node_name, data, run_node, settings):
    with run_node.parent():
        if "ShowText" in node_name:
            show_text_uptate(node_name, data)

        elif "PreviewImage" in node_name:
            preview_image_update(node_name, data, settings)

        elif "PyScript" in node_name:
            print(data["output"]["stdout"][0])


def show_text_uptate(node_name, data):
    output = data.get("output", {})
    texts = output.get("text", [])
    text = texts[0] if texts else ""

    show_text_node = nuke.toNode(node_name)

    if not show_text_node:
        return

    if not text:
        return

    text = text.replace("\n", "")
    text = text.encode("utf-8") if sys.version_info[0] < 3 else text
    formatted_text = "\n".join(textwrap.wrap(text, width=50))

    text_knob = show_text_node.knob("text")
    if text_knob:
        text_knob.setValue(text)

    output_text_node = nuke.toNode(node_name + "Output")
    if not output_text_node:
        return

    label = "( [value {}.name] )\n{}\n\n".format(node_name, formatted_text)
    output_text_node.knob("label").setValue(label)
    xpos = show_text_node.xpos() - output_text_node.screenWidth() - 50
    ypos = (
        show_text_node.ypos()
        - (output_text_node.screenHeight() / 2)
        + (show_text_node.screenHeight() / 2)
    )
    output_text_node.knob("label")
    output_text_node.setXYpos(xpos, ypos)


def preview_image_update(node_name, data, settings):
    output = data.get("output", {})
    images = output.get("images", [])

    if not images:
        return

    filename = images[0].get("filename")
    if not filename:
        return

    preview_node = nuke.toNode(node_name)
    if not preview_node:
        return

    preview_node.begin()

    filename = "{}/temp/{}".format(settings["COMFYUI_DIR"], filename)
    read = nuke.toNode("read")

    if not read:
        read = nuke.createNode("Read", inpanel=False)
        read.setName("read")

    read.knob("file").setValue(filename)
    nuke.toNode("Output1").setInput(0, read)

    preview_node.knob("postage_stamp").setValue(True)
    preview_node.end()


def submit(run_node, success_callback=None, settings=None):
    def success_callback_wrapper(read=None, run_node=None, error=None):
        if not success_callback:
            return

        if success_callback.__code__.co_argcount == 2:
            success_callback(read, run_node)
        elif success_callback.__code__.co_argcount == 3:
            success_callback(read, run_node, error)
        else:
            success_callback(read)

    if not settings:
        settings = get_settings(run_node)

    settings["pre_inference_time"] = time()
    # previene que exista el key cuando no se ejecuta en execution_start
    settings["inference_time"] = time()

    if not settings["INPUT_DIRECTORY"] or not settings["OUTPUT_DIRECTORY"]:
        message = (
            "INPUT_DIRECTORY or OUTPUT_DIRECTORY environment variables are not set!"
        )
        nuke.message(message)
        success_callback_wrapper(run_node=run_node, error=message)
        return

    pbar_status = {"title": "Inferencing", "progress": 0, "message": ""}
    pbar = [nuke.ProgressTask(pbar_status["title"])]

    def set_task_progress(progress, message="", include_ip=True):
        if not nuke.GUI:
            print("{} : {}%".format(message or pbar_status["message"], progress))

        if not pbar:
            return

        pbar[0].setProgress(progress)
        pbar_status["progress"] = progress

        if include_ip:
            ip = "" if "127" in settings["URL"] else get_ip_from_url(settings["URL"])
        else:
            ip = ""

        if message:
            if "Loop" in message:
                message = "{} - {}".format(
                    message.count("Loop") + 1, message.split(".")[-1]
                )

            message = "{} ({}) ".format(message, ip) if ip else message
            pbar[0].setMessage(message)
            pbar_status["message"] = message

    set_task_progress(0, "Scanning ComfyUI servers...", False)

    if not resolve_submission_target(settings):
        message = "No ComfyUI server available!"
        success_callback_wrapper(run_node=run_node, error=message)
        return

    if not update_images_and_mask_inputs():
        message = "Error connecting: the image and mask inputs were not refreshed!"
        show_message(message)
        success_callback_wrapper(run_node=run_node, error=message)
        return

    exr_filepath_fixed(run_node)
    settings["project_name"] = nuke.root().name()

    set_task_progress(0, "Rendering Nuke images...")

    data, input_node_changed = extract_data(run_node, settings)
    if not data:
        success_callback_wrapper(run_node=run_node, error="data")
        return

    if data == states.get(run_node.fullName(), {}) and not input_node_changed:
        settings["filename_prefix"] = update_filename_prefix(run_node, False)
        filename = resolve_filename(settings, True)
        read = create_read(run_node, data, settings, filename, already_exists=True)

        success_callback_wrapper(read, run_node)
        return

    settings["filename_prefix"] = update_filename_prefix(run_node, data=data)
    state_data = copy.deepcopy(data)

    global prompt_counter
    prompt_counter += 1
    user = os.path.basename(get_user_path())
    client_id = f"{user}:{get_project_name()}:{prompt_counter}".replace(" ", "-")

    body = {
        "client_id": client_id,
        "number": resolve_queue_position(settings, user),
        "prompt": data,
        "extra_data": {},
    }

    url = "{}/ws?clientId={}".format(settings["URL"].replace("http", "ws"), client_id)
    execution_error = [""]
    settings["pre_inference_time"] = time() - settings["pre_inference_time"]

    set_task_progress(0, "Waiting in Queue ...")

    def on_message(ws, message):
        try:
            message_size = len(message)
            if message_size > 1024 * 200:
                set_task_progress(50, "Waiting to finish...")
                ws.close()
                return

            message = json.loads(message)
        except Exception:
            return

        data = message.get("data", None)
        type_data = message.get("type", None)

        if not data:
            return

        elif type_data == "execution_start":
            settings["inference_time"] = time()

        elif type_data == "executed":
            node = data.get("node")
            execute_in_main_thread(update_node, args=(node, data, run_node, settings))

        elif type_data == "progress":
            progress = int(data["value"] * 100 / float(data["max"] or 0.01))
            set_task_progress(progress)

        elif type_data == "executing":
            node = data.get("node")

            if pbar:
                if node:
                    set_task_progress(0, node)
                else:
                    del pbar[0]

        elif type_data == "execution_error":
            execution_message = data.get("exception_message")
            error = "Error: {}\n\n".format(data.get("node_type"))
            error += execution_message + "\n\n"

            for tb in data.get("traceback"):
                error += tb + "\n"

            execution_error[0] = error

            if pbar:
                del pbar[0]

            execute_in_main_thread(
                error_node_style,
                args=(data.get("node_id"), True, execution_message, run_node),
            )
            show_message(error)

    def on_error(ws, error):
        ws.close()
        if pbar:
            del pbar[0]

        if "connected" in str(error):
            return

        execution_error[0] = "Error: {}".format(error)
        show_message(execution_error[0])

    def progress_task_loop():
        cancelled = False
        captured_prompt = False
        check_count = 0

        while pbar:
            if pbar[0].isCancelled():
                if nuke.executeInMainThreadWithResult(
                    lambda: nuke.ask(
                        "Are you sure? This will stop the ComfyUI inference"
                    )
                ):
                    cancelled = True
                    break
                elif pbar:
                    pbar[0] = nuke.ProgressTask(pbar_status["title"])
                    pbar[0].setProgress(pbar_status["progress"])
                    pbar[0].setMessage(pbar_status["message"])

            if check_count >= 10:
                # It prevents the websocket from getting stuck, especially in loops.
                if get_prompt_id(settings, client_id):
                    captured_prompt = True
                elif captured_prompt:
                    break
                check_count = 0

            sleep(0.1)
            check_count += 1

        interrupt(settings, client_id)

        if pbar:
            del pbar[0]

        ws.close()

        if cancelled:
            return

        filename = resolve_filename(settings)

        execute_in_main_thread(progress_finished, args=(run_node, filename))

    def progress_finished(n, filename):
        try:
            read = create_read(n, data, settings, filename)
            success_callback_wrapper(read, run_node, execution_error[0])

            if not execution_error[0]:
                remove_all_error_style(run_node)
                states[run_node.fullName()] = state_data

        except Exception:
            print(traceback.format_exc())
            show_message(traceback.format_exc())

    ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error)

    task_loop = None
    if not settings["BACKGROUND_SUBMIT"]:
        ws_thread = threading.Thread(target=ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()

        task_loop = threading.Thread(target=progress_task_loop)
        task_loop.daemon = True
        task_loop.start()

    error = POST("prompt", body, settings)

    if settings["BACKGROUND_SUBMIT"] and not error:
        read = create_empty_read(run_node, data, settings)
        success_callback_wrapper(read, run_node, execution_error[0])
        show_message(
            "Workflow sent to the ComfyUI Queue:\n\n{}".format(show_queue(False))
        )

    if error:
        execution_error[0] = error
        if pbar:
            del pbar[0]
        if settings["BACKGROUND_SUBMIT"]:
            success_callback_wrapper(run_node=run_node, error=error)
        show_message(error)

    if not nuke.GUI:
        task_loop.join() if task_loop else None
        print(
            "\nPrompt executed in {} seconds".format(
                round(time() - settings["inference_time"], 1)
            )
        )

    return settings
