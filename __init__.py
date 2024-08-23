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


path = os.path.join(NUKE_USER, 'nuke_comfyui')


def setup():
    icon = '{}/icons/comfyui_icon.png'.format(path)
    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI', icon=icon)

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(path)
    nodes_dir = os.path.join(path, 'nodes', 'ComfyUI')

    refresh_icon = '{}/icons/refresh.png'.format(path)
    comfyui_menu.addCommand(
        'Update all ComfyUI', update_menu.update, '', refresh_icon)

    def create_node(nk):
        node = nuke.nodePaste(os.path.join(nodes_dir, nk))
        node.showControlPanel()

    for nk in os.listdir(nodes_dir):
        name = 'Basic Nodes/' + nk.split('.')[0]
        comfyui_menu.addCommand(name, partial(create_node, nk), '', icon_gray)
