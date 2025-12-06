# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..nuke_util.nuke_util import get_output_nodes, get_input
from .run import submit
from .read_media import save_image_backup


def multi_runs(runs, success_callback=None, backup=False):
    if not runs:
        return

    run = runs.pop(0)
    aux = run

    if run.knob('comfyui_gizmo'):
        run = nuke.toNode(run.fullName() + '.Run')

    def on_success(read):
        if read:
            for i, n in get_output_nodes(aux):
                n.setInput(i, read)

        if backup:
            save_image_backup(run)

        if not runs and success_callback:
            success_callback()

        multi_runs(runs, success_callback, backup)

    submit(run, success_callback=on_success)


def multi_versions(run, versions, success_callback=None):
    for n in run.nodes():
        if versions > 1 and n.knob('randomize'):
            n.knob('randomize').setValue(True)

    runs = [run] * versions
    multi_runs(runs, success_callback, backup=True)


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

        if not inode.knob('run'):
            continue

        runs.append(inode)

    multi_runs(runs)
