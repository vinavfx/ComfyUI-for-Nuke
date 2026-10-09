# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import __main__

from .common import get_settings, wait_for_comfyui
from .nodes import get_external_input
from .run import submit


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
        code = callback.value()
        context = __main__.__dict__.copy()
        context["ret"] = True
        context["halt"] = False
        context["error"] = None
        context["metadata"] = {}
        context["iter"] = iteration
        context["node_iter"] = node_iteration
        nuke.message = capture_message
        try:
            exec(code, context)
        except Exception:
            for message in messages:
                original_message(message)
            raise
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
        linked = (
            source.getLinkedKnob() if hasattr(source, "getLinkedKnob") else None
        )
        if linked is not None and linked.name() == "comfyui_gizmo":
            visit(linked.node())
        else:
            for index in range(node.inputs()):
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
        from .execute_runs import multi_runs
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
    from .execute_runs import sequential_execution

    if dependency_nodes is None:
        dependency_nodes = []
        for gizmo in gizmos:
            if gizmo.knob("comfyui_gizmo") is not None:
                for dependency in dependency_gizmos(gizmo)[:-1]:
                    if dependency not in dependency_nodes:
                        dependency_nodes.append(dependency)

    def execution_finished(error):
        if error:
            nuke.message(error)
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

    ret, _, _, metadata = inference_start(run_node)
    if not ret:
        return

    if wait_for_comfyui(lambda: submit_run(run_node, metadata)):
        return

    submit_run(run_node, metadata)
