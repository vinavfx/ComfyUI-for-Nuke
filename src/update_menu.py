# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from functools import partial
import re
import nuke  # type: ignore

from ..nuke_util.nuke_util import get_nuke_path
from .connection import GET

path = '{}/nuke_comfyui'.format(get_nuke_path())


def create_node(data):
    n = nuke.createNode('Group')

    name = re.sub(r'\(.*?\)', '', data['name'])
    name = re.sub(r'[^a-zA-Z0-9]', '', name)
    n.setName(name)

    # Knobs
    for k, _input in data['input']['required'].items():

        if _input[0] == 'INT':
            knob = nuke.Int_Knob(k)
            n.addKnob(knob)

        elif type(_input[0]) == list:
            knob = nuke.Enumeration_Knob(k, k, _input[0])
            n.addKnob(knob)


def update():
    info = GET('object_info')
    if not info:
        return

    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI')
    nodes = {}

    for _, value in info.items():
        category = value['category']
        category = ''.join(char if ord(
            char) < 128 else '' for char in category)
        category = category.replace(' /', '/').replace('/ ', '/')

        name = value['name'].replace('+', '')

        item_name = '{}/{}'.format(category.strip(), name.strip())
        nodes[item_name] = value

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(path)

    for fullname, value in sorted(nodes.items()):
        comfyui_menu.addCommand(fullname, partial(
            create_node, value), '', icon_gray)
