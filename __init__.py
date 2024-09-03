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
from .env import NUKE_USER


update_menu_at_start = False
path = os.path.join(NUKE_USER, 'nuke_comfyui')


def setup():
    icon = '{}/icons/comfyui_icon.png'.format(path)
    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI', icon=icon)

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(path)
    nodes_dir = os.path.join(path, 'nodes')

    refresh_icon = '{}/icons/refresh.png'.format(path)
    basic_icon = '{}/icons/basic.png'.format(path)
    workflow_icon = '{}/icons/workflow.png'.format(path)
    gizmos_icon = '{}/icons/gizmos.png'.format(path)

    comfyui_menu.addCommand(
        'Update all ComfyUI', update_menu.update, '', refresh_icon)

    comfyui_menu.addCommand(
        'Import Workflow', workflow_importer.import_workflow, '', workflow_icon)

    comfyui_menu.addMenu('Basic Nodes', basic_icon)
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

    if update_menu_at_start:
        update_menu.update()
