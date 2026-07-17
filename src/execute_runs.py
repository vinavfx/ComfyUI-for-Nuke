# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import copy
import nuke  # type: ignore
import json
from ..nuke_util.nuke_util import selected_node
from .run import submit
from .cmd import inference_end, inference_start
from .common import get_settings, override_settings
from . import queue_manager
from .queue_manager import scan_urls, job_running_message, blocked_urls
from .connection import format_URLs


def get_run(run):
    if run.knob('comfyui_gizmo'):
        return nuke.toNode(run.fullName() + '.Run')

    return run


def multi_runs(runs, success_callback=None, settings=None, distribute_load=False):
    if len(runs) > 10:
        if not nuke.ask('Are you sure you want to queue {} tasks?'.format(len(runs))):
            return

    stop = [False]
    for i, run in enumerate(runs):
        if stop[0]:
            break

        run = get_run(run)

        if not inference_start(run, i):
            continue

        def on_success(read, _, error):
            if error:
                stop[0] = True
                if success_callback:
                    success_callback()
                return

            inference_end(read, run)

            if len(runs) == i + 1 and success_callback:
                success_callback()

        with run:
            settings = submit(run, success_callback=on_success,
                   settings=copy.deepcopy(settings) if settings else None)

        if distribute_load:
            settings = None

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


def execute_runs(settings=None, distribute_load=False):
    runs = []

    for n in nuke.selectedNodes():
        if not n.knob('run'):
            continue

        if n in runs:
            continue

        runs.extend(prepare_multiversions(n))

    if not runs:
        nuke.message('Select at least 1 Run node!')
        return

    multi_runs(runs, settings=settings, distribute_load=distribute_load)


def execute_runs_plus():
    nodes = selected_node(False)
    if not nodes:
        return

    settings = get_settings()
    all_urls = settings['URL']

    urls = ['-', '{%s}' % 'Distribute on all IPs']
    urls.extend(json.loads(settings['URL']))

    _, _, _, running_client, pending_client = scan_urls(settings)
    queue = job_running_message(running_client, pending_client)

    keys = [
        'URL',
        'Use this URL as primary',
        'Use EXR to laod images',
        'Display metadata in Read Node',
        'Background Submit',
        'Force scan URLs'
    ]

    p = nuke.Panel('Run')
    p.addEnumerationPulldown(keys[0], ' '.join(urls))
    p.addBooleanCheckBox(keys[1], False)
    p.addNotepad('Queue', queue)
    p.addBooleanCheckBox(keys[2], True)
    p.addBooleanCheckBox(keys[3], True)
    p.addBooleanCheckBox(keys[4], False)
    p.addBooleanCheckBox(keys[5], False)
    p.addButton('Cancel')
    p.addButton('Run')

    if not 'No inference' in queue:
        p.setWidth(500)

    if not p.show():
        return

    url = p.value(keys[0])
    distribute_load = 'Distribute' in url

    if url == '-':
        override_settings(get_run(nodes[0]), settings)
    elif distribute_load:
        settings['URL'] = all_urls
    else:
        settings['URL'] = url
        if p.value(keys[1]):
            queue_manager.primary_url = format_URLs(url)[0]

    settings['USE_EXR_TO_LOAD_IMAGES'] = p.value(keys[2])
    settings['DISPLAY_META_IN_READ_NODE'] = p.value(keys[3])
    settings['BACKGROUND_SUBMIT'] = p.value(keys[4])

    if p.value(keys[5]):
        blocked_urls.clear()

    execute_runs(settings, distribute_load)
