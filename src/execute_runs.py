# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import json
from ..nuke_util.nuke_util import get_output_nodes
from .run import submit
from .cmd import inference_end, inference_start
from .common import get_settings
from .queue_manager import scan_urls, job_running_message


def multi_runs(runs, success_callback=None, settings=None):
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

        multi_runs(runs, success_callback, settings)

    with run:
        submit(run, success_callback=on_success, settings=settings)


def multi_versions(run, versions, success_callback=None):
    for n in run.nodes():
        if versions > 1 and n.knob('randomize'):
            n.knob('randomize').setValue(True)

    runs = [run] * versions
    multi_runs(runs, success_callback)


def execute_runs(settings=None):
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

    multi_runs(runs, settings=settings)


def execute_runs_plus():
    settings = get_settings()
    urls = json.loads(settings['URL'])

    _, _, _, running_client, pending_client = scan_urls(settings)
    queue = job_running_message(running_client, pending_client)

    keys = [
        'URL',
        'Use EXR to laod images',
        'Display metadata in Read Node',
        'Backgroundi Submit'
    ]

    p = nuke.Panel('Run')
    p.addEnumerationPulldown(keys[0], ' '.join(urls))
    p.addNotepad('Queue', queue)
    p.addBooleanCheckBox(keys[1], False)
    p.addBooleanCheckBox(keys[2], True)
    p.addBooleanCheckBox(keys[3], False)
    p.addButton('Cancel')
    p.addButton('Run')

    if not p.show():
        return

    settings['URL'] = p.value(keys[0])
    settings['USE_EXR_TO_LOAD_IMAGES'] = p.value(keys[1])
    settings['DISPLAY_META_IN_READ_NODE'] = p.value(keys[2])
    settings['BACKGROUND_SUBMIT'] = p.value(keys[3])

    execute_runs(settings)
