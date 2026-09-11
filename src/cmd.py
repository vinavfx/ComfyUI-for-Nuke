# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import __main__

from .common import wait_for_comfyui
from .run import submit


def get_run(run):
    if run.knob("comfyui_gizmo"):
        return nuke.toNode(run.fullName() + ".Run")

    return run


def get_read(group=None):
    if nuke.GUI:
        return nuke.toNode(nuke.thisNode().fullName() + "Read")

    if not group:
        group = nuke.thisNode()

    for n in group.parent().nodes():
        if n.name() == group.name() + "Read":
            return n


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


def inference_end(_, run_node):
    if not run_node:
        return

    callback = run_node.parent().knob("inferenceEnd")
    if callback:
        callback.execute()


def submit_run(run_node, metadata):
    with run_node:
        submit(run_node, inference_end, custom_metadata=metadata)


def run():
    run_node = get_run(nuke.thisNode())
    ret, _, _, metadata = inference_start(run_node)
    if not ret:
        return

    if wait_for_comfyui(lambda: submit_run(run_node, metadata)):
        return

    submit_run(run_node, metadata)
