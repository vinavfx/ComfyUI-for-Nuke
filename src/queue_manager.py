# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import json
import re
import nuke  # type: ignore

from .connection import GET, POST
from .common import show_message


def job_running_message(running_client, pending_client):
    def ellipsis(s, n):
        return s if len(s) <= n else s[:n - 3] + "..."

    msg = '<b>Running</b>:\n'
    for i, client in enumerate(running_client):
        user, nk, send_id = (client.split(':') + [client, '', 1])[:3]
        msg += '    {} - <font color=orange>{}</font> : {} : <font color=#6cb56b>{}</font>\n'.format(
            i + 1, user, ellipsis(nk, 50), send_id)

    if pending_client:
        msg += '\n<b>Pending</b>:\n'
        for i, client in enumerate(pending_client):
            user, nk, send_id = (client.split(':') + [client, '', ''])[:3]
            msg += '    {} - <font color=orange>{}</font> : {} : <font color=#6cb56b>{}</font>\n'.format(
                i + 1, user, ellipsis(nk, 50), send_id)

    msg = "{}\n\nJobs running. Queue or run locally?\n<font color=#6cb56b>Yes = Queue / No = localhost".format(
        msg)

    return msg


def resolve_submission_target(settings, force_queue=None):
    url = settings['URL']
    urls = []

    pattern = r'^(https?://)?([a-zA-Z0-9.-]+|\d{1,3}(\.\d{1,3}){3})(:\d{1,5})?$'
    if re.match(pattern, url):
        urls = [url]
    else:
        try:
            urls = json.loads(url)
        except:
            show_message(
                '{}\nIt has to be an URL address or a list of URL addresses as JSON !'.format(url))
            return

    urls = [
        url if '://' in url else 'http://{}'.format(url)
        for url in urls
    ]

    available_url = ''
    lowest_load_url = None
    lowest_pending = 99999
    localhost_submit = False
    localhost = 'http://localhost:8188'

    running_client = []
    pending_client = []

    for url in urls:
        settings['URL'] = url
        queue = GET('queue', settings, warning=False, timeout=3)

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
        settings['URL'] = localhost
        localhost_submit = True

        if not GET('queue', settings, warning=False, timeout=2):
            show_message("{}\nNo ComfyUI servers found running !".format(
                ', '.join(urls + [settings['URL']])))
            return

    elif available_url:
        settings['URL'] = available_url

    else:
        try:
            if force_queue:
                if force_queue == 'localhost':
                    settings['URL'] = localhost
                    localhost_submit = True
                else:
                    settings['URL'] = lowest_load_url

            elif nuke.askWithCancel(job_running_message(running_client, pending_client)):
                settings['URL'] = lowest_load_url
            else:
                settings['URL'] = localhost
                localhost_submit = True
        except:
            return

    if settings['COMFYUI_LOCAL']:
        comfyui_dir = settings['COMFYUI_DIR']
        comfyui_dirs = []

        pattern = r'^[^\*\[\]]+$'
        if re.match(pattern, comfyui_dir):
            comfyui_dirs = [comfyui_dir]
        else:
            try:
                comfyui_dirs = json.loads(comfyui_dir)
            except:
                show_message(
                    '{}\nIt must be a ComfyUI directory or a list of ComfyUI directories in JSON format!'.format(comfyui_dir))
                return

        if not len(urls) == len(comfyui_dirs):
            comfyui_dirs = [comfyui_dirs[0]] * len(urls)

        settings['COMFYUI_DIR'] = dict(
            zip(urls, comfyui_dirs)).get(settings['URL'], '')

        if localhost_submit:
            settings['COMFYUI_DIR'] = comfyui_dirs[0]
        elif not settings['COMFYUI_DIR']:
            show_message(
                'URL "{}" without assigned ComfyUI directory !'.format(settings['URL']))
            return

    if not GET('system_stats', settings):
        return

    return settings


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
            show_message(error)
