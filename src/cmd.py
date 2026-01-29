# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore

from .run import submit


def get_read(group=None):
    if nuke.GUI:
        return nuke.toNode(nuke.thisNode().fullName() + 'Read')

    if not group:
        group = nuke.thisNode()

    for n in group.parent().nodes():
        if n.name() == group.name() + 'Read':
            return n


def inference_start(run_node):
    gizmo = run_node.parent()
    callback = gizmo.knob('inferenceStart')

    if not callback:
        return True

    with gizmo:
        code = callback.value()
        context = globals().copy()
        exec(code, context)
        return context.get('ret')


def inference_end(_, run_node):
    callback = run_node.parent().knob('inferenceEnd')
    if callback:
        callback.execute()


def run():
    run_node = nuke.thisNode()
    if inference_start(run_node) == False:
        return

    submit(run_node, inference_end)
