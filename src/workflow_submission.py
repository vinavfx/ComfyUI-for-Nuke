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
    calculate_queue_priority,
    resolve_submission_target,
    show_queue,
)
from .nodes import prepare_workflow_data
from .unified_workflow import extract_unified_data
from .generation_outputs import (
    create_read,
    prepare_output_path,
    find_inference_file,
    create_empty_read,
    register_temporary_inference,
)

error_node_style = ComfyJob.error_node_style
remove_all_error_style = ComfyJob.remove_all_error_style
update_node = ComfyJob.update_node
show_text_update = ComfyJob.show_text_update
preview_image_update = ComfyJob.preview_image_update
states = ComfyJob.states
prompt_counter = 0
inference_start_callbacks = []


def add_inference_start(callback):
    if callback not in inference_start_callbacks:
        inference_start_callbacks.append(callback)


def remove_inference_start(callback):
    if callback in inference_start_callbacks:
        inference_start_callbacks.remove(callback)


class SubmissionJob(ComfyJob):
    def __init__(
        self,
        run_node,
        result_callback=None,
        settings=None,
        last_error=None,
        validate_prompt=False,
        custom_metadata=None,
    ):
        settings = settings or get_settings(run_node)
        settings["custom_metadata"] = custom_metadata or {}
        super().__init__(run_node, settings)
        self.result_callback = result_callback
        self.last_error = last_error
        self.validate_prompt = validate_prompt

    def notify_submission_result(self, read=None, run_node=None, error=None):
        if not self.result_callback:
            return

        argument_count = self.result_callback.__code__.co_argcount
        if argument_count == 2:
            self.result_callback(read, run_node)
        elif argument_count == 3:
            self.result_callback(read, run_node, error)
        else:
            self.result_callback(read)

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
            "number": calculate_queue_priority(self.settings, user),
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
        self.notify_submission_result(read, self.run_node)

    def finish_failed(self, error):
        self.show_error(error)
        self.notify_submission_result(run_node=self.run_node, error=error)

    def start(self):
        settings = self.settings
        settings["pre_inference_time"] = time()
        settings["inference_time"] = time()

        if not settings["INPUT_DIRECTORY"] or not settings["OUTPUT_DIRECTORY"]:
            message = (
                "INPUT_DIRECTORY or OUTPUT_DIRECTORY environment variables are not set!"
            )
            self.close_progress()
            self.show_error(message)
            self.notify_submission_result(run_node=self.run_node, error=message)
            return

        self.set_progress(0, "Scanning ComfyUI servers...", False)
        if not resolve_submission_target(settings):
            message = "No ComfyUI server available!"
            self.close_progress()
            self.notify_submission_result(run_node=self.run_node, error=message)
            return

        if not update_images_and_mask_inputs():
            message = (
                "Could not discover image and mask inputs: "
                "ComfyUI node information is unavailable."
            )
            self.close_progress()
            self.show_error(message)
            self.notify_submission_result(run_node=self.run_node, error=message)
            return

        self.set_progress(0, "Rendering Nuke images...")

        gizmo = self.run_node.parent()
        if gizmo.knob("comfyui_gizmo") is not None:
            current_group = nuke.thisGroup()
            try:
                with gizmo:
                    for callback in tuple(inference_start_callbacks):
                        callback(self.run_node)
            finally:
                current_group.begin()

        extract = (
            extract_unified_data
            if settings.get("UNIFIED_WORKFLOW")
            else prepare_workflow_data
        )
        data, input_node_changed, error_message = extract(
            self.run_node,
            settings,
        )
        if not data:
            self.close_progress()
            self.notify_submission_result(
                run_node=self.run_node,
                error=error_message,
            )
            return

        node_name = self.run_node.fullName()
        if (
            not self.validate_prompt
            and data == states.get(node_name, {})
            and not input_node_changed
        ):
            output_path = prepare_output_path(
                self.run_node,
                settings,
                update=False,
                data=data,
            )
            read = None
            if output_path:
                filename = find_inference_file(settings)
                read = create_read(
                    self.run_node,
                    data,
                    settings,
                    filename,
                    already_exists=True,
                )
            self.close_progress()
            self.notify_submission_result(read, self.run_node)
            return

        output_path = prepare_output_path(
            self.run_node,
            settings,
            data=data,
        )
        self.data = data
        if not self.validate_prompt and output_path:
            register_temporary_inference(self.run_node, data, settings)

        settings["pre_inference_time"] = time() - settings["pre_inference_time"]
        body = self.create_request_body()

        if self.validate_prompt:
            self.set_progress(0, "Validating workflow...")
            error = POST(
                "comfyui_nuke/validate_prompt",
                body,
                settings,
            )
            self.close_progress()
            if error:
                self.finish_with_error(error)
            else:
                self.notify_submission_result(run_node=self.run_node)
            return settings

        self.set_progress(0, "Waiting in Queue ...")
        if not settings["BACKGROUND_SUBMIT"]:
            self.start_monitor()

        error = POST("prompt", body, settings)
        if settings["BACKGROUND_SUBMIT"] and not error:
            self.close_progress()
            read = None
            if output_path:
                read = create_empty_read(self.run_node, data, settings)
            self.notify_submission_result(
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
            elapsed = round(time() - settings["inference_time"], 1)
            if self.cancelled:
                print("\nPrompt cancelled after {} seconds".format(elapsed))
            elif error or self.execution_error:
                print("\nPrompt failed after {} seconds".format(elapsed))
            elif settings["BACKGROUND_SUBMIT"]:
                print("\nPrompt submitted to the ComfyUI queue")
            else:
                print("\nPrompt completed successfully in {} seconds".format(elapsed))

        return settings


def submit(
    run_node,
    result_callback=None,
    settings=None,
    last_error=None,
    validate_prompt=False,
    custom_metadata=None,
):
    job = SubmissionJob(
        run_node,
        result_callback,
        settings,
        last_error,
        validate_prompt,
        custom_metadata,
    )
    return job.start()
