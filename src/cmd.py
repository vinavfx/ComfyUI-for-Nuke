# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import __main__

from .run import submit


def get_read(group=None):
    if nuke.GUI:
        return nuke.toNode(nuke.thisNode().fullName() + 'Read')

    if not group:
        group = nuke.thisNode()

    for n in group.parent().nodes():
        if n.name() == group.name() + 'Read':
            return n


def inference_start(run_node, iteration=0):
    gizmo = run_node.parent()
    callback = gizmo.knob('inferenceStart')

    if not callback:
        return True

    with gizmo:
        code = callback.value()
        context = __main__.__dict__.copy()
        context['ret'] = True
        context['iter'] = iteration
        exec(code, context)
        return context.get('ret')


def inference_end(_, run_node):
    if not run_node:
        return

    callback = run_node.parent().knob('inferenceEnd')
    if callback:
        callback.execute()


def run():
    run_node = nuke.thisNode()
    if not inference_start(run_node):
        return

    with run_node:
        submit(run_node, inference_end)
