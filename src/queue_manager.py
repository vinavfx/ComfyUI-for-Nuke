# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from concurrent.futures import ThreadPoolExecutor, as_completed
import nuke  # type: ignore

from .connection import GET, POST, format_URLs, get_ip_from_url
from .common import show_message, get_settings


blocked_urls = []
primary_url = None
scan_timeout = 3


def scan_urls(settings):
    urls = format_URLs(settings["URL"])

    if not urls:
        show_message(f"{settings['URL']}\nIt has to be an URL address or a list of URL addresses as JSON!")
        return [None] * 5

    lowest_load_url = None
    lowest_pending = 99999

    running_client = []
    pending_client = []
    available_urls = []

    online_urls = 0
    active_urls = [u for u in urls if u not in blocked_urls]

    with ThreadPoolExecutor(max_workers=min(30, len(active_urls) or 1)) as executor:
        futures = {
            executor.submit(GET, "queue", {"URL": url}, warning=False, timeout=scan_timeout): (i, url)
            for i, url in enumerate(active_urls)
        }

        results = []
        for future in as_completed(futures):
            i, url = futures[future]
            results.append((i, url, future.result()))

        results.sort(key=lambda x: x[0])

        for _, url, queue in results:
            if not queue:
                blocked_urls.append(url)
                continue

            online_urls += 1

            running = queue["queue_running"]
            pending = queue["queue_pending"]

            if len(pending) < lowest_pending:
                lowest_pending = len(pending)
                lowest_load_url = url

            if not running:
                available_urls.append(url)

            running_client += [(url, r[3]["client_id"]) for r in running]
            pending_client += [(url, p[3]["client_id"], p[0]) for p in pending]

    pending_client.sort(key=lambda x: x[2])
    pending_client = [(url, client_id) for url, client_id, _ in pending_client]

    if primary_url and primary_url in available_urls:
        available_url = primary_url
    elif available_urls:
        available_url = available_urls[0]
    else:
        available_url = None

    if not online_urls:
        blocked_urls.clear()

    return urls, available_url, lowest_load_url, running_client, pending_client


def resolve_queue_position(settings, new_user):
    queue = GET("queue", settings)
    if not queue:
        return 1

    items = []
    for i in queue["queue_pending"]:
        user = i[3]["client_id"].split(":")[0]
        prio = float(i[0])
        items.append((user, prio))

    items.sort(key=lambda x: x[1])

    counts = {}
    rounds = []
    for user, prio in items:
        r = counts.get(user, 0)
        rounds.append(r)
        counts[user] = r + 1

    target_round = counts.get(new_user, 0)

    insert_index = None
    for i, r in enumerate(rounds):
        if r > target_round:
            insert_index = i
            break

    if insert_index is None:
        last_prio = items[-1][1] if items else 0
        return last_prio + 1
    else:
        prev_prio = items[insert_index - 1][1] if insert_index > 0 else 0
        next_prio = items[insert_index][1]
        return (prev_prio + next_prio) / 2


def resolve_submission_target(settings):
    urls, available_url, lowest_load_url, _, _ = scan_urls(settings)
    if not urls:
        return

    if not available_url and not lowest_load_url:
        show_message("No ComfyUI servers found running!\n{}".format("\n".join(urls)))
        return

    elif available_url:
        settings["URL"] = available_url

    else:
        settings["URL"] = lowest_load_url

    if not GET("system_stats", settings, timeout=scan_timeout):
        return

    return settings


def job_running_message(running_client, pending_client):
    def ellipsis(s, n):
        return s if len(s) <= n else s[: n - 3] + "..."

    msgline = (
        "    {} - <font color=orange>{}</font> : <font color=#4FC3F7>{}</font> : {} : <font color=#6cb56b>{}</font>\n"
    )
    msg = ""

    if running_client:
        msg = "<b>Running</b>:\n"
        for i, (url, client) in enumerate(running_client):
            user, nk, send_id = (client.split(":") + [client, "", 1])[:3]
            ip = get_ip_from_url(url)
            msg += msgline.format(i + 1, user, ip, ellipsis(nk, 35), send_id)

    if pending_client:
        msg += "\n<b>Pending</b>:\n"
        for i, (url, client) in enumerate(pending_client):
            user, nk, send_id = (client.split(":") + [client, "", ""])[:3]
            ip = get_ip_from_url(url)
            msg += msgline.format(i + 1, user, ip, ellipsis(nk, 35), send_id)

    if not msg:
        msg = "No inference is executed!"

    msg = "<span style='white-space: pre;'>{}</span>".format(msg)

    return msg


def show_queue(nuke_message=True):
    settings = get_settings()
    _, _, _, running_client, pending_client = scan_urls(settings)

    queue = job_running_message(running_client, pending_client)
    if nuke_message:
        nuke.message(queue)

    return queue


def find_prompt_id(queue_list, client_id):
    return next((r[1] for r in queue_list if r[3].get("client_id") == client_id), "")


def get_prompt_id(settings, client_id):
    queue = GET("queue", settings)
    if not queue:
        return

    prompt_id = find_prompt_id(queue["queue_running"], client_id)

    if not prompt_id:
        prompt_id = find_prompt_id(queue["queue_pending"], client_id)

    return prompt_id


def interrupt(settings, client_id):
    queue = GET("queue", settings)
    if not queue:
        return

    prompt_id = find_prompt_id(queue["queue_running"], client_id)
    endpoint = "interrupt" if prompt_id else "queue"

    if not prompt_id:
        prompt_id = find_prompt_id(queue["queue_pending"], client_id)

    if prompt_id:
        error = POST(endpoint, {"delete": [prompt_id]}, settings)
        if error:
            show_message(error)
