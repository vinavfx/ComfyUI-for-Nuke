# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
from .src import *
from .testing import *
from functools import partial
from .settings import UPDATE_MENU_AT_START, COMFYUI2NUKE


def setup():
    icon = '{}/icons/comfyui_icon.png'.format(COMFYUI2NUKE)
    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI', icon=icon)

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(COMFYUI2NUKE)
    nodes_dir = os.path.join(COMFYUI2NUKE, 'nodes')

    refresh_icon = '{}/icons/refresh.png'.format(COMFYUI2NUKE)
    basic_icon = '{}/icons/basic.png'.format(COMFYUI2NUKE)
    workflow_icon = '{}/icons/workflow.png'.format(COMFYUI2NUKE)
    gizmos_icon = '{}/icons/gizmos.png'.format(COMFYUI2NUKE)
    scripts_icon = '{}/icons/scripts.png'.format(COMFYUI2NUKE)

    comfyui_menu.addCommand(
        'Update all ComfyUI', update_menu.update, '', refresh_icon)

    comfyui_menu.addCommand(
        'Import Workflow', workflow_importer.import_workflow, '', workflow_icon)

    comfyui_menu.addMenu('Basic Nodes', basic_icon)
    comfyui_menu.addMenu('Scripts', scripts_icon)
    comfyui_menu.addMenu('Gizmos', gizmos_icon)

    def create_node(nk):
        node = nuke.nodePaste(os.path.join(nodes_dir, nk))
        node.showControlPanel()

    for dirname in os.listdir(nodes_dir):
        folder = os.path.join(nodes_dir, dirname)

        if not os.path.isdir(folder):
            continue

        for nk in os.listdir(folder):
            if not nk.split('.')[-1] == 'nk':
                continue

            name = '{}/{}'.format('Basic Nodes' if dirname ==
                                  'ComfyUI' else dirname, nk.split('.')[0])

            path_nk = os.path.join(folder, nk)
            comfyui_menu.addCommand(name, partial(
                create_node, path_nk), '', icon_gray)

    comfyui_menu.addCommand(
        'Scripts/knob2input', scripts.knob2input.knob_to_input, icon=icon_gray)

    comfyui_menu.addCommand(
        'Scripts/forceOutput', scripts.force_output_connection.force_output, icon=icon_gray)

    comfyui_menu.addCommand(
        'Scripts/exportWorkflow', scripts.export_workflow.export_workflow, icon=icon_gray)

    if UPDATE_MENU_AT_START:
        update_menu.update()
