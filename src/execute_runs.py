# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import json
from ..nuke_util.nuke_util import get_output_nodes, selected_node
from .run import submit
from .cmd import inference_end, inference_start
from .common import get_settings
from .queue_manager import scan_urls, job_running_message


def multi_runs(runs, success_callback=None, settings=None):
    for i, run in enumerate(runs):
        if run.knob('comfyui_gizmo'):
            run = nuke.toNode(run.fullName() + '.Run')

        if not inference_start(run, i):
            continue

        def on_success(read, _, error):
            if error:
                if success_callback:
                    success_callback()
                return

            if read:
                for inp, n in get_output_nodes(run):
                    n.setInput(inp, read)

            inference_end(read, run)

            if len(runs) == i + 1 and success_callback:
                success_callback()

        with run:
            submit(run, success_callback=on_success, settings=settings)
        run.end()


def multi_versions(run=None, success_callback=None):
    if not run:
        run = nuke.thisNode()

    multi_runs(prepare_multiversions(run), success_callback)


def prepare_multiversions(node):
    versions = 1
    if node.knob('versions'):
        versions = int(node.knob('versions').value())

    for child in node.nodes():
        if versions > 1 and child.knob('randomize'):
            child.knob('randomize').setValue(True)

    return [node] * versions


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

        runs.extend(prepare_multiversions(n))

    if not runs:
        nuke.message('Select at least 1 Run node!')
        return

    multi_runs(runs, settings=settings)


def execute_runs_plus():
    if not selected_node():
        return

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
