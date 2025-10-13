# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..nuke_util.nuke_util import get_output_nodes, get_input
from .run import submit


def multi_runs(runs):
    if not runs:
        return

    run = runs.pop(0)
    aux = run

    if run.knob('comfyui_gizmo'):
        run = nuke.toNode(run.name() + '.Run')

    def on_success(read):
        if read:
            for i, n in get_output_nodes(aux):
                n.setInput(i, read)

        multi_runs(runs)

    submit(run, success_callback=on_success)


def execute_runs():
    runs = []
    this = nuke.thisNode()
    for i in range(this.inputs()):
        inode = get_input(this, i)

        if not inode:
            continue

        if inode.Class() == 'Read':
            qp_name = inode.name().replace('Read', '')
            qp = nuke.toNode(qp_name)
            if qp:
                runs.append(qp)
                continue

        if not inode.knob('comfyui_submit'):
            continue

        runs.append(inode)

    multi_runs(runs)
