# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import __main__
import copy

import nuke  # type: ignore
from ..nuke_util.selection import get_selected_nodes
from .workflow_submission import submit
from .nodes import get_external_input
from .common import (
    get_settings,
    override_settings,
    wait_for_comfyui,
    init_scan_thread,
    show_message,
)
from . import queue_manager
from .queue_manager import scan_urls, job_running_message, blocked_urls


def get_run(run):
    if run.knob("comfyui_gizmo"):
        return nuke.toNode(run.fullName() + ".Run")

    return run


def inference_start(run_node, iteration=0, node_iteration=0):
    gizmo = run_node.parent()
    callback = gizmo.knob("inferenceStart")

    if not callback:
        return True, False, None, {}

    messages = []
    original_message = nuke.message

    def capture_message(message):
        messages.append(str(message))

    with gizmo:
        context = __main__.__dict__.copy()
        context["ret"] = True
        context["halt"] = False
        context["error"] = None
        context["metadata"] = {}
        context["iter"] = iteration
        context["node_iter"] = node_iteration
        nuke.message = capture_message
        try:
            exec(callback.value(), context)
        except Exception as error:
            messages.append(str(error) or type(error).__name__)
            return False, True, "\n".join(messages), {}
        finally:
            nuke.message = original_message

    error = context.get("error")
    if not error and messages:
        error = "\n".join(messages)

    return context.get("ret"), context.get("halt"), error, context["metadata"]


def inference_end(read, run_node, *, iteration=0, node_iteration=0):
    if not run_node:
        return

    gizmo = run_node.parent()
    callback = gizmo.knob("inferenceEnd")
    if not callback:
        return

    context = __main__.__dict__.copy()
    context["read"] = read
    context["iter"] = iteration
    context["node_iter"] = node_iteration
    with gizmo:
        exec(callback.value(), context)


def submit_run(run_node, metadata):
    with run_node:
        submit(run_node, inference_end, custom_metadata=metadata)


def dependency_input_indices(node):
    if node.Class() != "Group" or node.knob("comfyui_gizmo") is not None:
        return range(node.inputs())

    return sorted(
        {
            int(input_node["number"].value())
            for child in node.nodes()
            for index in range(child.inputs())
            if (input_node := child.input(index)) is not None
            and input_node.Class() == "Input"
        }
    )


def dependency_gizmos(gizmo):
    ordered = []
    visited = set()
    visiting = set()

    def visit(node):
        name = node.fullName()
        if name in visiting:
            raise ValueError("Circular gizmo dependency: {}".format(name))
        if name in visited:
            return

        visiting.add(name)
        source = node.knobs().get("comfyui_source")
        linked = source.getLinkedKnob() if hasattr(source, "getLinkedKnob") else None
        if linked is not None and linked.name() == "comfyui_gizmo":
            visit(linked.node())
        else:
            for index in dependency_input_indices(node):
                upstream = get_external_input(node, index)
                if upstream is not None:
                    visit(upstream)

        visiting.remove(name)
        visited.add(name)
        if node.knob("comfyui_gizmo") is not None:
            ordered.append(node)

    visit(gizmo)
    return ordered


def confirm_dependencies(gizmo):
    try:
        gizmos = dependency_gizmos(gizmo)
    except ValueError as error:
        nuke.message(str(error))
        return None
    if len(gizmos) <= 1:
        return []
    return confirm_dependency_order(gizmos, [gizmo])


def missing_dependency_outputs(gizmos):
    missing = []
    visited = set()

    def visit(node):
        if node is None or node.fullName() in visited:
            return
        visited.add(node.fullName())
        if node.Class() in ("Read", "ReadGeo", "ReadGeo2"):
            return
        if node.knob("comfyui_gizmo") is not None:
            missing.append(node.fullName())
            return
        for index in range(node.inputs()):
            visit(get_external_input(node, index))

    for gizmo in gizmos:
        for index in range(gizmo.inputs()):
            visit(get_external_input(gizmo, index))
    return list(dict.fromkeys(missing))


def confirm_dependency_order(gizmos, selected_gizmos, settings=None):
    names = "\n".join(
        "{}. {}".format(index + 1, node.fullName()) for index, node in enumerate(gizmos)
    )
    panel = nuke.Panel("Run connected ComfyUI gizmos")
    submission_modes = [
        "Unified workflow",
        "Separate workflows (Read per gizmo)",
        "Selected gizmos only",
    ]
    choices = " ".join(mode.replace(" ", "\\ ") for mode in submission_modes)
    panel.addEnumerationPulldown("Submission", choices)
    panel.addNotepad("Dependency order", names)
    if not panel.show():
        return None
    mode = panel.value("Submission")
    if mode == "Separate workflows (Read per gizmo)":
        return gizmos
    if mode == "Unified workflow":
        from .unified_workflow import unified_gizmos

        try:
            for gizmo in selected_gizmos:
                unified_gizmos(gizmo)
        except ValueError as error:
            nuke.message(str(error))
            return None
        unified_settings = dict(settings or get_settings(get_run(selected_gizmos[0])))
        unified_settings["UNIFIED_WORKFLOW"] = True
        multi_runs(selected_gizmos, settings=unified_settings)
        return None
    missing = missing_dependency_outputs(selected_gizmos)
    if missing:
        nuke.message(
            "These dependencies must run first because they are connected "
            "as gizmos rather than rendered Read nodes:\n\n"
            + "\n".join(missing)
        )
        return None
    return []


def run_dependencies(
    gizmos, success_callback=None, settings=None, dependency_nodes=None
):
    if dependency_nodes is None:
        dependency_nodes = []
        for gizmo in gizmos:
            if gizmo.knob("comfyui_gizmo") is not None:
                for dependency in dependency_gizmos(gizmo)[:-1]:
                    if dependency not in dependency_nodes:
                        dependency_nodes.append(dependency)

    def execution_finished(error):
        if error:
            show_message(error)
        elif success_callback:
            success_callback()

    def execute():
        sequential_execution(
            gizmos,
            callback=execution_finished,
            settings=settings,
            dependency_nodes=dependency_nodes,
        )

    if wait_for_comfyui(execute):
        return
    execute()


def run():
    run_node = get_run(nuke.thisNode())
    gizmo = run_node.parent()
    if gizmo.knob("comfyui_gizmo") is not None:
        gizmos = confirm_dependencies(gizmo)
        if gizmos is None:
            return
        if gizmos:
            run_dependencies(gizmos)
            return

    ret, halt, start_error, metadata = inference_start(run_node)
    if start_error:
        show_message(start_error)
    if halt or not ret:
        return

    if wait_for_comfyui(lambda: submit_run(run_node, metadata)):
        return

    submit_run(run_node, metadata)


def cli_submit(gizmos, callback=None, validate_prompt=False):
    init_scan_thread()
    sequential_execution(gizmos, callback=callback, validate_prompt=validate_prompt)


def sequential_execution(
    gizmos=None,
    error=None,
    callback=None,
    index=0,
    validate_prompt=False,
    settings=None,
    dependency_nodes=None,
):
    if gizmos is None:
        gizmos = []
    if dependency_nodes is None:
        dependency_nodes = []

    while not error and index < len(gizmos):
        gizmo = gizmos[index]
        run = get_run(gizmo)
        node_iteration = gizmos[:index].count(gizmo)
        ret, halt, start_error, metadata = inference_start(run, index, node_iteration)
        if halt or not ret:
            if start_error:
                error = start_error
                if not callback:
                    show_message(error)
            else:
                status = "halted" if halt else "rejected"
                error = "Inference start {} execution for node '{}'.".format(
                    status, run.parent().fullName()
                )
            break

        if not validate_prompt:

            def execution_finished(read, run_node, execution_error):
                if not execution_error:
                    inference_end(
                        read,
                        run_node,
                        iteration=index,
                        node_iteration=node_iteration,
                    )
                sequential_execution(
                    gizmos,
                    execution_error,
                    callback,
                    index + 1,
                    settings=settings,
                    dependency_nodes=dependency_nodes,
                )

            run_settings = copy.deepcopy(settings) if settings else get_settings(run)
            run_settings["BACKGROUND_SUBMIT"] = False
            run_settings["LINK_DEPENDENCY_SOURCE"] = gizmo in dependency_nodes
            with run:
                submit(
                    run,
                    result_callback=execution_finished,
                    settings=run_settings,
                    custom_metadata=metadata,
                )
            return

        validation_errors = []

        def validation_finished(read, run_node, validation_error):
            del read, run_node
            validation_errors.append(validation_error)

        with run:
            submit(
                run,
                result_callback=validation_finished,
                validate_prompt=True,
                custom_metadata=metadata,
            )
        run.end()
        error = validation_errors[0] if validation_errors else None
        index += 1

    if callback:
        callback(error or None)


def multi_runs(runs, success_callback=None, settings=None, distribute_load=False):
    if wait_for_comfyui(
        lambda: multi_runs(runs, success_callback, settings, distribute_load)
    ):
        return

    if len(runs) > 10:
        if not nuke.ask("Are you sure you want to queue {} tasks?".format(len(runs))):
            return

    stop = [False]
    last_error = [""]
    iterations = {}

    def create_success_callback(run_node, run_index, node_iteration):
        def on_success(read, _, error):
            if error:
                stop[0] = True
                if success_callback:
                    success_callback()
                return

            inference_end(
                read,
                run_node,
                iteration=run_index,
                node_iteration=node_iteration,
            )

            if len(runs) == run_index + 1 and success_callback:
                success_callback()

        return on_success

    for i, run in enumerate(runs):
        if stop[0]:
            break

        node_name = run.name()
        iteration = iterations.get(node_name, 0)
        iterations[node_name] = iteration + 1
        run = get_run(run)

        ret, halt, start_error, metadata = inference_start(run, i, iteration)
        if start_error:
            show_message(start_error)
        if halt:
            break
        if not ret:
            continue

        on_success = create_success_callback(run, i, iteration)
        with run:
            settings = submit(
                run,
                result_callback=on_success,
                settings=copy.deepcopy(settings) if settings else None,
                last_error=last_error,
                custom_metadata=metadata,
            )

        if distribute_load:
            settings = None

        run.end()


def multi_versions(run=None, success_callback=None):
    if not run:
        run = nuke.thisNode()

    if run.knob("comfyui_gizmo") is not None:
        gizmos = confirm_dependencies(run)
        if gizmos is None:
            return
        if gizmos:
            runs = gizmos[:-1] + prepare_multiversions(run)
            run_dependencies(runs, success_callback)
            return

    multi_runs(prepare_multiversions(run), success_callback)


def prepare_multiversions(node):
    batch = 1
    if node.knob("batch"):
        batch = int(node.knob("batch").value())

    for child in node.nodes():
        if batch > 1 and child.knob("randomize"):
            child.knob("randomize").setValue(True)

    return [node] * batch


def execute_runs(settings=None, distribute_load=False):
    runs = []
    has_meta = False

    for n in nuke.selectedNodes():
        if not n.knob("run"):
            continue

        if n.knob("comfyui_meta_gizmo") is not None:
            from ..nodes.ComfyUI import MetaGizmo

            MetaGizmo.run(n, settings=settings)
            has_meta = True
            continue

        if n in runs:
            continue

        runs.extend(prepare_multiversions(n))

    if not runs:
        if not has_meta:
            nuke.message("Select at least 1 Run node!")
        return

    ordered = []
    has_dependencies = False
    try:
        for run in runs:
            dependencies = [run]
            if run.knob("comfyui_gizmo") is not None:
                dependencies = dependency_gizmos(run)
                has_dependencies = has_dependencies or len(dependencies) > 1
            for dependency in dependencies:
                if dependency not in ordered:
                    ordered.append(dependency)
    except ValueError as error:
        nuke.message(str(error))
        return

    if has_dependencies:
        confirmed = confirm_dependency_order(ordered, runs, settings=settings)
        if confirmed is None:
            return
        if confirmed:
            ordered_runs = []
            for node in confirmed:
                ordered_runs.extend([node] * max(runs.count(node), 1))
            run_dependencies(ordered_runs, settings=settings)
            return

    multi_runs(runs, settings=settings, distribute_load=distribute_load)


def execute_runs_plus():
    nodes = get_selected_nodes()
    if not nodes:
        return

    settings = get_settings()
    all_urls = settings["URL"]

    urls = ["-", "{%s}" % "Distribute on all IPs"]
    urls.extend(settings["URL"])

    _, _, _, running_client, pending_client = scan_urls(settings)
    queue = job_running_message(running_client, pending_client)

    keys = [
        "URL",
        "Use this URL as primary",
        "Display metadata in Read Node",
        "Background Submit",
        "Force scan URLs",
    ]

    p = nuke.Panel("Run")
    p.addEnumerationPulldown(keys[0], " ".join(urls))
    p.addBooleanCheckBox(keys[1], False)
    p.addNotepad("Queue", queue)
    p.addBooleanCheckBox(keys[2], True)
    p.addBooleanCheckBox(keys[3], False)
    p.addBooleanCheckBox(keys[4], False)
    p.addButton("Cancel")
    p.addButton("Run")

    if "No inference" not in queue:
        p.setWidth(500)

    if not p.show():
        return

    url = p.value(keys[0])
    distribute_load = "Distribute" in url

    if url == "-":
        override_settings(get_run(nodes[0]), settings)
    elif distribute_load:
        settings["URL"] = all_urls
    else:
        settings["URL"] = [url]
        if p.value(keys[1]):
            queue_manager.primary_url = url

    settings["DISPLAY_META_IN_READ_NODE"] = p.value(keys[2])
    settings["BACKGROUND_SUBMIT"] = p.value(keys[3])

    if p.value(keys[4]):
        blocked_urls.clear()

    execute_runs(settings, distribute_load)
