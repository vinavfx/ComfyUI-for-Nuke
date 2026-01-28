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
    callback = run_node.parent().knob('inferenceStart')
    if callback:
        callback.execute()


def inference_end(_, run_node):
    callback = run_node.parent().knob('inferenceEnd')
    if callback:
        callback.execute()


def run():
    run_node = nuke.thisNode()
    inference_start(run_node)
    submit(run_node, inference_end)
