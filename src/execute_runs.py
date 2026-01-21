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
from .cmd import inference_end


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

        inference_end(read, run)
        if not runs:
            if success_callback:
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
            run_name = n.name().replace('Read', '')
            run = nuke.toNode(run_name)

            if run and not run in runs:
                runs.append(run)
                continue

        if not n.knob('run'):
            continue

        if n in runs:
            continue

        versions = 1
        if n.knob('versions'):
            versions = int(n.knob('versions').value())

        for child in n.nodes():
            if versions > 1 and child.knob('randomize'):
                child.knob('randomize').setValue(True)

        runs.extend([n] * versions)

    multi_runs(runs)
