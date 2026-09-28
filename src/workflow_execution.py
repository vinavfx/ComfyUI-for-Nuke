from random import randrange
from time import time

import nuke  # type: ignore

from .cmd import inference_end, inference_start
from .common import (
    image_inputs,
    mask_inputs,
    show_message,
    update_images_and_mask_inputs,
    wait_for_comfyui,
)
from .connection import POST
from .nodes import create_load_images_and_save, extract_node_data, get_node_data
from .queue_manager import resolve_submission_target, show_queue
from .read_media import (
    create_empty_read,
    exr_filepath_fixed,
    register_temporary_inference,
    update_filename_prefix,
)
from .run import SubmissionJob
from .workflow_connections import resolve_workflow_input


def workflow_node_id(node):
    return "root." + node.fullName()


def workflow_output_slot(node, node_data, index, source, slot):
    input_data = node_data["inputs"][index]
    outputs = get_node_data(source).get("outputs", [])
    allowed = input_data["outputs"]
    forced = input_data.get("force_output", slot)
    if forced is not None:
        if forced < 0 or forced >= len(outputs):
            raise ValueError("Invalid output slot on {}".format(source.fullName()))
        if "*" not in allowed and outputs[forced] not in allowed + ["*"]:
            raise ValueError("Incompatible input on {}".format(node.fullName()))
        return forced
    matches = [
        index
        for index, output in enumerate(outputs)
        if output in allowed or "*" in allowed or output == "*"
    ]
    if len(matches) != 1:
        raise ValueError(
            "Select an output for {} on {}".format(input_data["name"], node.fullName())
        )
    return matches[0]


def extract_workflow(run_node, settings):
    output, _ = resolve_workflow_input(run_node, 0)
    if not output or not get_node_data(output).get("output_node"):
        raise ValueError("Connect Run to an output node such as SaveImage or SaveEXR.")
    nuke.root()["proxy"].setValue(False)
    pending = [output]
    visited = set()
    rendered = set()
    data = {}
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        node_data = get_node_data(node)
        randomize = node.knob("randomize")
        if randomize and randomize.value():
            for name in ("seed_", "noise_seed_", "value_"):
                knob = node.knob(name)
                if knob:
                    knob.setValue(randrange(1, 9999))
                    break
        body = extract_node_data(node)
        for index, input_data in enumerate(node_data["inputs"]):
            if input_data.get("ignore"):
                continue
            source, slot = resolve_workflow_input(node, index)
            name = input_data["name"]
            if not source:
                if input_data.get("opt"):
                    continue
                raise ValueError("{}.{} is disconnected.".format(node.fullName(), name))
            source_data = get_node_data(source)
            if source_data:
                slot = workflow_output_slot(node, node_data, index, source, slot)
                pending.append(source)
            elif name in image_inputs + mask_inputs:
                source_id = workflow_node_id(source)
                if source_id not in data:
                    with nuke.Root():
                        loaded, _, canceled = create_load_images_and_save(
                            source, settings, rendered
                        )
                    if canceled:
                        raise ValueError("Image rendering was canceled.")
                    data[source_id] = loaded
                slot = 1 if name in mask_inputs else 0
            else:
                raise ValueError(
                    "{}.{} has an unsupported source.".format(node.fullName(), name)
                )
            body["inputs"][name] = [workflow_node_id(source), slot]
        data[workflow_node_id(node)] = body
    return data


class WorkflowSubmissionJob(SubmissionJob):
    def start(self):
        settings = self.settings
        started = time()
        settings["pre_inference_time"] = started
        settings["inference_time"] = started
        try:
            if not settings["INPUT_DIRECTORY"] or not settings["OUTPUT_DIRECTORY"]:
                raise ValueError("INPUT_DIRECTORY and OUTPUT_DIRECTORY must be set.")
            self.set_progress(0, "Scanning ComfyUI servers...", False)
            if not resolve_submission_target(settings):
                raise ValueError("No ComfyUI server available.")
            if not update_images_and_mask_inputs():
                raise ValueError("Could not refresh image and mask inputs.")
            exr_filepath_fixed(self.run_node)
            settings["project_name"] = nuke.root().name()
            self.set_progress(0, "Preparing imported workflow...")
            self.data = extract_workflow(self.run_node, settings)
            output, _ = resolve_workflow_input(self.run_node, 0)
            if not output:
                raise ValueError("Run is disconnected.")
            output_data = {output.name(): self.data[workflow_node_id(output)]}
            settings["filename_prefix"] = update_filename_prefix(
                self.run_node, data=output_data
            )
            if settings["filename_prefix"]:
                register_temporary_inference(self.run_node, self.data, settings)
            settings["pre_inference_time"] = time() - started
            body = self.create_request_body()
            self.set_progress(0, "Waiting in Queue ...")
            if not settings["BACKGROUND_SUBMIT"]:
                self.start_monitor()
            error = POST("prompt", body, settings)
            if error:
                if self.monitor_thread:
                    self.set_external_error(error)
                else:
                    self.close_progress()
                    self.finish_with_error(error)
            elif settings["BACKGROUND_SUBMIT"]:
                self.close_progress()
                read = None
                if settings["filename_prefix"]:
                    read = create_empty_read(self.run_node, self.data, settings)
                self.run_success_callback(read, self.run_node, self.execution_error)
                show_message(
                    "Workflow sent to the ComfyUI Queue:\n\n" + show_queue(False)
                )
            if not nuke.GUI and self.monitor_thread:
                self.wait()
            return settings
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            self.close_progress()
            self.show_error(str(error))
            self.run_success_callback(run_node=self.run_node, error=str(error))


def submit_workflow(run_node, metadata):
    job = WorkflowSubmissionJob(
        run_node, success_callback=inference_end, custom_metadata=metadata
    )
    return job.start()


def run_workflow(run_node):
    proceed, _, _, metadata = inference_start(run_node)
    if not proceed:
        return
    if wait_for_comfyui(lambda: submit_workflow(run_node, metadata)):
        return
    return submit_workflow(run_node, metadata)
