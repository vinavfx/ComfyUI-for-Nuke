# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..nuke_util.nuke_util import get_output_nodes
from .run import submit
from .cmd import inference_end, inference_start


def multi_runs(runs, success_callback=None):
    if not runs:
        return

    run = runs.pop(0)
    aux = run

    if run.knob('comfyui_gizmo'):
        run = nuke.toNode(run.fullName() + '.Run')

    if not inference_start(run):
        return

    def on_success(read, _, error):
        if error:
            if success_callback:
                success_callback()
            return

        if read:
            for i, n in get_output_nodes(aux):
                n.setInput(i, read)

        inference_end(read, run)
        if not runs and success_callback:
            success_callback()

        multi_runs(runs, success_callback)

    with run:
        submit(run, success_callback=on_success)


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
