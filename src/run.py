# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
from time import time

import nuke  # type: ignore

from ..nuke_util.nuke_util import get_project_name, get_user_path
from .common import get_settings, show_message, update_images_and_mask_inputs
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

error_node_style = ComfyJob.error_node_style
remove_all_error_style = ComfyJob.remove_all_error_style
update_node = ComfyJob.update_node
show_text_uptate = ComfyJob.show_text_update
preview_image_update = ComfyJob.preview_image_update
states = ComfyJob.states
prompt_counter = 0


class SubmissionJob(ComfyJob):
    def __init__(
        self,
        run_node,
        success_callback=None,
        settings=None,
        last_error=None,
    ):
        settings = settings or get_settings(run_node)
        super().__init__(run_node, settings)
        self.success_callback = success_callback
        self.last_error = last_error

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

    def finish_succeeded(self, read):
        self.run_success_callback(read, self.run_node)

    def finish_failed(self, error):
        self.show_error(error)
        self.run_success_callback(run_node=self.run_node, error=error)

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
                self.close_progress()
                self.finish_with_error(error)

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
