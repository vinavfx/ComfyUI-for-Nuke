# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
from .src import *
from .nuke_util.nuke_util import get_nuke_path
from functools import partial


path = '{}/nuke_comfyui'.format(get_nuke_path())


def setup():

    icon = '{}/icons/comfyui_icon.png'.format(path)
    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI', icon=icon)

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(path)
    nodes_dir = os.path.join(path, 'nodes')

    def create_node(nk):
        node = nuke.nodePaste(os.path.join(nodes_dir, nk))
        node.showControlPanel()

    for nk in os.listdir(nodes_dir):
        name = nk.split('.')[0]
        comfyui_menu.addCommand(name, partial(create_node, nk), '', icon_gray)
