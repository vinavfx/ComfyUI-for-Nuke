# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import copy
import os
import sys
import textwrap
import traceback
from time import time

import nuke  # type: ignore

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
from .comfy_job import ComfyJob
from .connection import POST
from .queue_manager import (
    resolve_queue_position,
    resolve_submission_target,
    show_queue,
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


class SubmissionJob(ComfyJob):
    def __init__(
        self,
        run_node,
        success_callback=None,
        settings=None,
        last_error=None,
    ):
        settings = settings or get_settings(run_node)
        super().__init__(run_node, settings, update_node)
        self.success_callback = success_callback
        self.last_error = last_error
        self.state_data = None

    def run_success_callback(self, read=None, run_node=None, error=None):
        if not self.success_callback:
            return

        argument_count = self.success_callback.__code__.co_argcount
        if argument_count == 2:
            self.success_callback(read, run_node)
        elif argument_count == 3:
            self.success_callback(read, run_node, error)
        else:
            self.success_callback(read)

    def show_error(self, message):
        if self.last_error is None:
            show_message(message)
            return

        if message == self.last_error[0]:
            return

        self.last_error[0] = message
        show_message(message)

    def create_request_body(self):
        global prompt_counter
        prompt_counter += 1

        user = os.path.basename(get_user_path())
        project_name = get_project_name()
        client_id = "{}:{}:{}".format(user, project_name, prompt_counter)
        self.client_id = client_id.replace(" ", "-")

        recovery_data = {
            "run_node": self.run_node.fullName(),
            "settings": dict(self.settings),
        }
        return {
            "client_id": self.client_id,
            "number": resolve_queue_position(self.settings, user),
            "prompt": self.data,
            "extra_data": {"comfyui2nuke": recovery_data},
        }

    def format_execution_error(self, message_data):
        execution_message = message_data.get("exception_message")
        if not execution_message:
            execution_message = "ComfyUI execution failed."

        error = "Error: {}\n\n".format(message_data.get("node_type"))
        error += execution_message + "\n\n"
        for traceback_line in message_data.get("traceback") or []:
            error += traceback_line + "\n"
        return error

    def report_error(self, message, message_data=None):
        if message_data:
            execution_message = message_data.get("exception_message") or ""
            execute_in_main_thread(
                error_node_style,
                args=(
                    message_data.get("node_id"),
                    True,
                    execution_message,
                    self.run_node,
                ),
            )
        self.show_error(message)

    def finish(self):
        try:
            filename = resolve_filename(self.settings)
            read = create_read(
                self.run_node,
                self.data,
                self.settings,
                filename,
            )
            self.run_success_callback(
                read,
                self.run_node,
                self.execution_error,
            )

            if not self.execution_error:
                remove_all_error_style(self.run_node)
                states[self.run_node.fullName()] = self.state_data
        except Exception:
            error = traceback.format_exc()
            print(error)
            self.show_error(error)

    def start(self):
        settings = self.settings
        settings["pre_inference_time"] = time()
        settings["inference_time"] = time()

        if not settings["INPUT_DIRECTORY"] or not settings["OUTPUT_DIRECTORY"]:
            message = (
                "INPUT_DIRECTORY or OUTPUT_DIRECTORY environment variables "
                "are not set!"
            )
            self.close_progress()
            self.show_error(message)
            self.run_success_callback(run_node=self.run_node, error=message)
            return

        self.set_progress(0, "Scanning ComfyUI servers...", False)
        if not resolve_submission_target(settings):
            message = "No ComfyUI server available!"
            self.close_progress()
            self.run_success_callback(run_node=self.run_node, error=message)
            return

        if not update_images_and_mask_inputs():
            message = "Error connecting: the image and mask inputs were not refreshed!"
            self.close_progress()
            self.show_error(message)
            self.run_success_callback(run_node=self.run_node, error=message)
            return

        exr_filepath_fixed(self.run_node)
        settings["project_name"] = nuke.root().name()
        self.set_progress(0, "Rendering Nuke images...")

        data, input_node_changed, error_message = extract_data(
            self.run_node,
            settings,
        )
        if not data:
            self.close_progress()
            self.run_success_callback(
                run_node=self.run_node,
                error=error_message,
            )
            return

        node_name = self.run_node.fullName()
        if data == states.get(node_name, {}) and not input_node_changed:
            settings["filename_prefix"] = update_filename_prefix(
                self.run_node,
                False,
            )
            filename = resolve_filename(settings, True)
            read = create_read(
                self.run_node,
                data,
                settings,
                filename,
                already_exists=True,
            )
            self.close_progress()
            self.run_success_callback(read, self.run_node)
            return

        settings["filename_prefix"] = update_filename_prefix(
            self.run_node,
            data=data,
        )
        self.data = data
        self.state_data = copy.deepcopy(data)
        settings["pre_inference_time"] = time() - settings["pre_inference_time"]
        body = self.create_request_body()

        self.set_progress(0, "Waiting in Queue ...")
        if not settings["BACKGROUND_SUBMIT"]:
            self.start_monitor()

        error = POST("prompt", body, settings)
        if settings["BACKGROUND_SUBMIT"] and not error:
            self.close_progress()
            read = create_empty_read(self.run_node, data, settings)
            self.run_success_callback(
                read,
                self.run_node,
                self.execution_error,
            )
            show_message(
                "Workflow sent to the ComfyUI Queue:\n\n{}".format(show_queue(False))
            )

        if error:
            if self.monitor_thread:
                self.set_external_error(error)
            else:
                self.execution_error = error
                self.close_progress()
                self.run_success_callback(
                    run_node=self.run_node,
                    error=error,
                )
            self.show_error(error)

        if not nuke.GUI:
            self.wait()
            print(
                "\nPrompt executed in {} seconds".format(
                    round(time() - settings["inference_time"], 1)
                )
            )

        return settings


def submit(run_node, success_callback=None, settings=None, last_error=None):
    job = SubmissionJob(
        run_node,
        success_callback,
        settings,
        last_error,
    )
    return job.start()
