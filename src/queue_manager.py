# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore

from .connection import GET, POST, format_URLs, get_ip_from_url
from .common import show_message, get_settings


def job_running_message(running_client, pending_client):
    def ellipsis(s, n):
        return s if len(s) <= n else s[:n - 3] + "..."

    msgline = '    {} - <font color=orange>{}</font> : <font color=#4FC3F7>{}</font> : {} : <font color=#6cb56b>{}</font>\n'
    msg = ''

    if running_client:
        msg = '<b>Running</b>:\n'
        for i, (url, client) in enumerate(running_client):
            user, nk, send_id = (client.split(':') + [client, '', 1])[:3]
            ip = get_ip_from_url(url)
            msg += msgline.format(i + 1, user, ip, ellipsis(nk, 35), send_id)

    if pending_client:
        msg += '\n<b>Pending</b>:\n'
        for i, (url, client) in enumerate(pending_client):
            user, nk, send_id = (client.split(':') + [client, '', ''])[:3]
            ip = get_ip_from_url(url)
            msg += msgline.format(i + 1, user, ip, ellipsis(nk, 35), send_id)

    if not msg:
        msg = 'No inference is executed!'

    msg = "<span style='white-space: pre;'>{}</span>".format(msg)

    return msg


def show_queue():
    settings = get_settings()
    _, _, _, running_client, pending_client = scan_urls(settings)
    nuke.message(job_running_message(running_client, pending_client))


blocked_urls = []


def scan_urls(settings):
    urls = format_URLs(settings['URL'])

    if not urls:
        show_message(
            '{}\nIt has to be an URL address or a list of URL addresses as JSON !'.format(settings['URL']))
        return [None] * 5

    available_url = ''
    lowest_load_url = None
    lowest_pending = 99999

    running_client = []
    pending_client = []
    online_urls = []

    for url in urls:
        if url in blocked_urls:
            continue

        settings['URL'] = url
        queue = GET('queue', settings, warning=False, timeout=3)

        if not queue:
            blocked_urls.append(url)
            continue

        online_urls.append(url)

        running = queue['queue_running']
        pending = queue['queue_pending']

        if len(pending) < lowest_pending:
            lowest_pending = len(pending)
            lowest_load_url = url

        if not available_url and not running:
            available_url = url

        running_client += [(url, r[3]['client_id']) for r in running]
        pending_client += [(url, p[3]['client_id']) for p in pending]

    if not online_urls:
        blocked_urls.clear()

    return urls, available_url, lowest_load_url, running_client, pending_client


def resolve_submission_target(settings):
    urls, available_url, lowest_load_url, _, _ = scan_urls(settings)
    if not urls:
        return

    if not available_url and not lowest_load_url:
        show_message("No ComfyUI servers found running !\n\n{}".format('\n'.join(urls)))
        return

    elif available_url:
        settings['URL'] = available_url

    else:
        settings['URL'] = lowest_load_url

    if not GET('system_stats', settings):
        return

    return settings


def find_prompt_id(queue_list, client_id):
    return next((r[1] for r in queue_list if r[3].get('client_id') == client_id), '')


def get_prompt_id(settings, client_id):
    queue = GET('queue', settings)
    if not queue:
        return

    prompt_id = find_prompt_id(queue['queue_running'], client_id)

    if not prompt_id:
        prompt_id = find_prompt_id(queue['queue_pending'], client_id)

    return prompt_id


def interrupt(settings, client_id):
    queue = GET('queue', settings)
    if not queue:
        return

    prompt_id = find_prompt_id(queue['queue_running'], client_id)
    endpoint = 'interrupt' if prompt_id else 'queue'

    if not prompt_id:
        prompt_id = find_prompt_id(queue['queue_pending'], client_id)

    if prompt_id:
        error = POST(endpoint, {'delete': [prompt_id]}, settings)
        if error:
            show_message(error)
