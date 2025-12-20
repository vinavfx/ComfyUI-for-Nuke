# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..nuke_util.nuke_util import get_output_nodes
from .run import submit
from .queue_manager import resolve_submission_target
from .common import get_settings


def multi_runs(runs, success_callback=None, force_queue=None):
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

        if not runs and success_callback:
            success_callback()

        multi_runs(runs, success_callback, force_queue)

    if not force_queue:
        settings = get_settings(run)
        settings = resolve_submission_target(settings)
        if not settings:
            return

        force_queue = 'localhost' if 'localhost' in settings['URL'] else 'server'

    submit(run, success_callback=on_success, force_queue=force_queue)


def multi_versions(run, versions, success_callback=None):
    for n in run.nodes():
        if versions > 1 and n.knob('randomize'):
            n.knob('randomize').setValue(True)

    runs = [run] * versions
    multi_runs(runs, success_callback)


def execute_runs():
    runs = []

    for n in nuke.selectedNodes():
        if n.Class() == 'Read':
            qp_name = n.name().replace('Read', '')
            qp = nuke.toNode(qp_name)
            if qp:
                runs.append(qp)
                continue

        if not n.knob('run'):
            continue

        runs.append(n)

    multi_runs(runs)
