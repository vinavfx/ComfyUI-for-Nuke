# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import __main__
import threading
from time import monotonic, sleep

from . import common
from .common import execute_in_main_thread, get_object_info
from .run import submit

COMFYUI_LOAD_TIMEOUT = 120
COMFYUI_LOAD_INTERVAL = 0.1


def get_run(run):
    if run.knob("comfyui_gizmo"):
        return nuke.toNode(run.fullName() + ".Run")

    return run


def get_read(group=None):
    if nuke.GUI:
        return nuke.toNode(nuke.thisNode().fullName() + "Read")

    if not group:
        group = nuke.thisNode()

    for n in group.parent().nodes():
        if n.name() == group.name() + "Read":
            return n


def inference_start(run_node, iteration=0):
    gizmo = run_node.parent()
    callback = gizmo.knob("inferenceStart")

    if not callback:
        return True

    with gizmo:
        code = callback.value()
        context = __main__.__dict__.copy()
        context["ret"] = True
        context["iter"] = iteration
        exec(code, context)
        return context.get("ret")


def inference_end(_, run_node):
    if not run_node:
        return

    callback = run_node.parent().knob("inferenceEnd")
    if callback:
        callback.execute()


def close_waiting_progress(progress):
    if progress:
        del progress[0]


def submit_run(run_node):
    with run_node:
        submit(run_node, inference_end)


def start_after_comfyui(callback, progress):
    close_waiting_progress(progress)
    callback()


def comfyui_load_timed_out(progress):
    close_waiting_progress(progress)
    get_object_info()


def wait_for_comfyui_load(callback, progress):
    started_at = monotonic()
    while common.object_info is None:
        if nuke.executeInMainThreadWithResult(progress[0].isCancelled):
            execute_in_main_thread(close_waiting_progress, (progress,))
            return

        elapsed = monotonic() - started_at
        if elapsed >= COMFYUI_LOAD_TIMEOUT:
            execute_in_main_thread(comfyui_load_timed_out, (progress,))
            return

        sleep(COMFYUI_LOAD_INTERVAL)

    execute_in_main_thread(start_after_comfyui, (callback, progress))


def wait_for_comfyui(callback):
    if common.object_info is not None:
        return False

    progress = [nuke.ProgressTask("Waiting for ComfyUI")]
    progress[0].setMessage("Waiting for ComfyUI to load...")
    progress[0].setProgress(0)
    threading.Thread(
        target=wait_for_comfyui_load,
        args=(callback, progress),
        daemon=True,
    ).start()
    return True


def run():
    run_node = get_run(nuke.thisNode())
    if not inference_start(run_node):
        return

    if wait_for_comfyui(lambda: submit_run(run_node)):
        return

    submit_run(run_node)
