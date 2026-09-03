# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import threading
import nuke  # type: ignore
from .src import (
    cmd,
    common,
    console,
    execute_runs,
    queue_manager,
    queue_recovery,
    read_media,
    scripts,
    update_menu,
    workflow_importer,
)
from functools import partial
from .settings import UPDATE_MENU_AT_START, COMFYUI2NUKE


def setup():
    threading.Thread(target=common.init_scan_thread, daemon=True).start()

    icon = "{}/icons/comfyui_icon.png".format(COMFYUI2NUKE)
    comfyui_menu = nuke.menu("Nodes").addMenu("ComfyUI", icon=icon)

    icon_gray = "{}/icons/comfyui_icon_gray.png".format(COMFYUI2NUKE)
    nodes_dir = os.path.join(COMFYUI2NUKE, "nodes")

    refresh_icon = "{}/icons/refresh.png".format(COMFYUI2NUKE)
    basic_icon = "{}/icons/basic.png".format(COMFYUI2NUKE)
    workflow_icon = "{}/icons/workflow.png".format(COMFYUI2NUKE)
    gizmos_icon = "{}/icons/gizmos.png".format(COMFYUI2NUKE)
    scripts_icon = "{}/icons/scripts.png".format(COMFYUI2NUKE)
    console_icon = "{}/icons/console.png".format(COMFYUI2NUKE)

    comfyui_menu.addCommand("Update all ComfyUI", update_menu.update, "", refresh_icon)

    comfyui_menu.addCommand(
        "Import Workflow", workflow_importer.import_workflow, "", workflow_icon
    )

    comfyui_menu.addMenu("Basic Nodes", basic_icon)
    comfyui_menu.addMenu("Scripts", scripts_icon)
    comfyui_menu.addMenu("Gizmos", gizmos_icon)

    def create_node(nk):
        node = nuke.nodePaste(os.path.join(nodes_dir, nk))
        node.showControlPanel()

    for dirname in os.listdir(nodes_dir):
        folder = os.path.join(nodes_dir, dirname)

        if not os.path.isdir(folder):
            continue

        for nk in os.listdir(folder):
            if not nk.split(".")[-1] == "nk":
                continue

            name = "{}/{}".format(
                "Basic Nodes" if dirname == "ComfyUI" else dirname, nk.split(".")[0]
            )

            path_nk = os.path.join(folder, nk)
            comfyui_menu.addCommand(name, partial(create_node, path_nk), "", icon_gray)

    comfyui_menu.addCommand(
        "Scripts/Knob to Input", scripts.knob2input.knob_to_input, icon=icon_gray
    )

    comfyui_menu.addCommand(
        "Scripts/Force Output",
        scripts.force_output_connection.force_output,
        icon=icon_gray,
    )

    comfyui_menu.addCommand(
        "Scripts/Force ComfyUI Scan",
        common.force_comfyui_scan,
        icon=icon_gray,
    )

    comfyui_menu.addCommand(
        "Scripts/Export Workflow",
        scripts.export_workflow.export_workflow,
        icon=icon_gray,
    )

    comfyui_menu.addCommand(
        "Scripts/Copy Workflow", scripts.export_workflow.copy_workflow, icon=icon_gray
    )

    comfyui_menu.addCommand(
        "Scripts/Execute Runs", execute_runs.execute_runs, "Ctrl+R", icon=icon_gray
    )

    comfyui_menu.addCommand(
        "Scripts/Execute Runs +",
        execute_runs.execute_runs_plus,
        "Ctrl+Shift+R",
        icon=icon_gray,
    )

    comfyui_menu.addCommand(
        "Scripts/Show Queue", queue_manager.show_queue, icon=icon_gray
    )

    comfyui_menu.addCommand(
        "Scripts/Restore Queue Progress",
        queue_recovery.restore_queue_progress,
        icon=icon_gray,
    )

    comfyui_menu.addCommand("Scripts/Show Data", scripts.show_data, icon=icon_gray)

    comfyui_menu.addCommand(
        "Scripts/Reload Node", scripts.reload_node.reload_node, icon=icon_gray
    )

    comfyui_menu.addCommand(
        "Scripts/Restore RunNode Generations",
        read_media.restore_run_generations,
        icon=icon_gray,
    )

    comfyui_menu.addCommand("Console", console.show_console, icon=console_icon)

    if UPDATE_MENU_AT_START:
        update_menu.update()
