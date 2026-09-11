# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import copy
import nuke  # type: ignore
from ..nuke_util.nuke_util import selected_node
from .run import submit
from .cmd import get_run, inference_end, inference_start
from .common import get_settings, override_settings, wait_for_comfyui, init_scan_thread
from . import queue_manager
from .queue_manager import scan_urls, job_running_message, blocked_urls
from .connection import get_ip_from_url
from ..settings import ALLOW_ALL_IPS_SUBMIT


def cli_submit(gizmos, callback=None, validate_prompt=False):
    init_scan_thread()
    sequential_execution(gizmos, callback=callback, validate_prompt=validate_prompt)


def sequential_execution(
    gizmos=None, error=None, callback=None, index=0, validate_prompt=False
):
    if gizmos is None:
        gizmos = []

    while not error and index < len(gizmos):
        gizmo = gizmos[index]
        run = get_run(gizmo)
        ret, halt, start_error, metadata = inference_start(
            run, index, gizmos[:index].count(gizmo)
        )
        if halt or not ret:
            if start_error:
                error = start_error
            else:
                status = "halted" if halt else "rejected"
                error = "Inference start {} execution for node '{}'.".format(
                    status, run.parent().fullName()
                )
            break

        if not validate_prompt:

            def execution_finished(read, run_node, execution_error):
                del read, run_node
                sequential_execution(gizmos, execution_error, callback, index + 1)

            submit(
                run,
                success_callback=execution_finished,
                custom_metadata=metadata,
            )
            return

        validation_errors = []

        def validation_finished(read, run_node, validation_error):
            del read, run_node
            validation_errors.append(validation_error)

        with run:
            submit(
                run,
                success_callback=validation_finished,
                validate_prompt=True,
                custom_metadata=metadata,
            )
        run.end()
        error = validation_errors[0] if validation_errors else None
        index += 1

    if callback:
        callback(error or None)


def multi_runs(runs, success_callback=None, settings=None, distribute_load=False):
    if wait_for_comfyui(
        lambda: multi_runs(runs, success_callback, settings, distribute_load)
    ):
        return

    if len(runs) > 10:
        if not nuke.ask("Are you sure you want to queue {} tasks?".format(len(runs))):
            return

    stop = [False]
    last_error = [""]
    iterations = {}
    for i, run in enumerate(runs):
        if stop[0]:
            break

        node_name = run.name()
        iteration = iterations.get(node_name, 0)
        iterations[node_name] = iteration + 1
        run = get_run(run)

        ret, halt, _, metadata = inference_start(run, i, iteration)
        if halt:
            break
        if not ret:
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
            settings = submit(
                run,
                success_callback=on_success,
                settings=copy.deepcopy(settings) if settings else None,
                last_error=last_error,
                custom_metadata=metadata,
            )

        if distribute_load:
            settings = None

        run.end()


def multi_versions(run=None, success_callback=None):
    if not run:
        run = nuke.thisNode()

    multi_runs(prepare_multiversions(run), success_callback)


def prepare_multiversions(node):
    versions = 1
    if node.knob("versions"):
        versions = int(node.knob("versions").value())

    for child in node.nodes():
        if versions > 1 and child.knob("randomize"):
            child.knob("randomize").setValue(True)

    return [node] * versions


def execute_runs(settings=None, distribute_load=False):
    runs = []

    for n in nuke.selectedNodes():
        if not n.knob("run"):
            continue

        if n in runs:
            continue

        runs.extend(prepare_multiversions(n))

    if not runs:
        nuke.message("Select at least 1 Run node!")
        return

    multi_runs(runs, settings=settings, distribute_load=distribute_load)


def execute_runs_plus():
    nodes = selected_node(False)
    if not nodes:
        return

    settings = get_settings()
    all_urls = settings["URL"]

    urls = ["-", "{%s}" % "Distribute on all IPs"]
    urls.extend(settings["URL"])

    _, _, _, running_client, pending_client = scan_urls(settings)
    queue = job_running_message(running_client, pending_client)

    keys = [
        "URL",
        "Use this URL as primary",
        "Use EXR to laod images",
        "Display metadata in Read Node",
        "Background Submit",
        "Force scan URLs",
    ]

    p = nuke.Panel("Run")
    p.addEnumerationPulldown(keys[0], " ".join(urls))
    p.addBooleanCheckBox(keys[1], False)
    p.addNotepad("Queue", queue)
    p.addBooleanCheckBox(keys[2], True)
    p.addBooleanCheckBox(keys[3], True)
    p.addBooleanCheckBox(keys[4], False)
    p.addBooleanCheckBox(keys[5], False)
    p.addButton("Cancel")
    p.addButton("Run")

    if "No inference" not in queue:
        p.setWidth(500)

    if not p.show():
        return

    url = p.value(keys[0])
    distribute_load = "Distribute" in url

    if url == "-":
        override_settings(get_run(nodes[0]), settings)
    elif distribute_load:
        settings["URL"] = all_urls
    else:
        settings["URL"] = [url]
        if p.value(keys[1]):
            queue_manager.primary_url = url

    settings["USE_EXR_TO_LOAD_IMAGES"] = p.value(keys[2])
    settings["DISPLAY_META_IN_READ_NODE"] = p.value(keys[3])
    settings["BACKGROUND_SUBMIT"] = p.value(keys[4])

    if p.value(keys[5]):
        blocked_urls.clear()

    current_ips = {
        get_ip_from_url(u)
        for u in settings["URL"]
        if not get_ip_from_url(u).startswith("127")
    }

    non_permitted = set()
    for node in nodes:
        node_settings = copy.deepcopy(settings)
        override_settings(get_run(node), node_settings)
        allowed = {get_ip_from_url(u) for u in node_settings["URL"]}
        non_permitted |= current_ips - allowed

    if non_permitted and not ALLOW_ALL_IPS_SUBMIT:
        node_names = ", ".join([n.name() for n in nodes])
        nuke.message(
            "These IPs are not allowed for nodes [{}]:\n{}".format(
                node_names, "\n".join(sorted(non_permitted))
            )
        )
        return

    execute_runs(settings, distribute_load)
