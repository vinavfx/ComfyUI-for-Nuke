# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import json
import re
import os
import nuke  # type: ignore

from .connection import GET, POST

def resolve_submission_target(settings):
    url = settings['URL']
    urls = []

    pattern = r'^(https?://)?([a-zA-Z0-9.-]+|\d{1,3}(\.\d{1,3}){3})(:\d{1,5})?$'
    if re.match(pattern, url):
        urls = [url]
    else:
        try:
            urls = json.loads(url)
        except:
            nuke.message(
                '{}\nIt has to be an URL address or a list of URL addresses as JSON !'.format(url))
            return

    urls = [
        url if '://' in url else 'http://{}'.format(url)
        for url in urls
    ]

    comfyui_dir = settings['COMFYUI_DIR']
    comfyui_dirs = []

    if os.path.exists(comfyui_dir):
        comfyui_dirs = [comfyui_dir]
    else:
        try:
            comfyui_dirs = json.loads(comfyui_dir)
        except:
            nuke.message(
                '{}\nIt must be a ComfyUI directory or a list of ComfyUI directories in JSON format!'.format(comfyui_dir))
            return

    if not len(urls) == len(comfyui_dirs):
        comfyui_dirs = [comfyui_dirs[0]] * len(urls)

    available_url = ''
    lowest_load_url = None
    lowest_pending = 99999

    running_client = []
    pending_client = []

    for url in urls:
        settings['URL'] = url
        queue = GET('queue', settings, warning=False, timeout=1)

        if not queue:
            continue

        running = queue['queue_running']
        pending = queue['queue_pending']

        if len(pending) < lowest_pending:
            lowest_pending = len(pending)
            lowest_load_url = url

        if not available_url and not running:
            available_url = url

        running_client += [r[3]['client_id'] for r in running]
        pending_client += [p[3]['client_id'] for p in pending]

    if not available_url and not lowest_load_url:
        nuke.message(
            "{}\nNo ComfyUI servers found running !".format(', '.join(urls)))
        return

    elif available_url:
        settings['URL'] = available_url

    else:
        msg = 'Running:\n'
        for i, client in enumerate(running_client):
            msg += '    {} - {}\n'.format(i+1, client)

        if pending_client:
            msg += '\nPending:\n'
            for i, client in enumerate(pending_client):
                msg += '    {} - {}\n'.format(i+1, client)

        ms = "{}\n\nThere are running inferences !".format(msg)
        panel = nuke.Panel('Submit')
        panel.addEnumerationPulldown(
            ms, "Send\\ to\\ Queue\nSend\\ to\\ localhost")
        panel.addButton("No")
        panel.addButton("Submit anyway ?")

        if panel.show():
            choice = panel.value(ms)
            if choice == 'Send to Queue':
                settings['URL'] = lowest_load_url
            else:
                settings['URL'] = 'http://0.0.0.0:8188'
        else:
            return

    settings['COMFYUI_DIR'] = dict(zip(urls, comfyui_dirs)).get(settings['URL'], '')
    if not settings['COMFYUI_DIR']:
        nuke.message(
            'URL "{}" without assigned ComfyUI directory !'.format(settings['URL']))
        return

    if not GET('system_stats', settings):
        return

    return True


def interrupt(settings, client_id):
    queue = GET('queue', settings)
    if not queue:
        return

    def find_prompt_id(queue_list):
        return next((r[1] for r in queue_list if r[3].get('client_id') == client_id), '')

    prompt_id = find_prompt_id(queue['queue_running'])
    endpoint = 'interrupt' if prompt_id else 'queue'

    if not prompt_id:
        prompt_id = find_prompt_id(queue['queue_pending'])

    if prompt_id:
        error = POST(endpoint, {'delete': [prompt_id]}, settings)
        if error:
            nuke.message(error)
