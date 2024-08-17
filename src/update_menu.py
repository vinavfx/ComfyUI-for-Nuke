# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from functools import partial
import re
import nuke  # type: ignore

from ..python_util.util import jprint
from ..nuke_util.nuke_util import get_nuke_path
from .connection import GET

path = '{}/nuke_comfyui'.format(get_nuke_path())


def create_node(data):
    n = nuke.createNode('Group')

    name = re.sub(r'\(.*?\)', '', data['name'])
    name = re.sub(r'[^a-zA-Z0-9]', '', name)
    n.setName(name)

    # Knobs
    for k in data['input_order']['required']:
        _input = data['input']['required'][k]

        _class = _input[0]
        info = _input[1] if len(_input) == 2 else {}

        tooltip = info.get('tooltip', '')
        default_value = info.get('default', 0)

        if _class == 'INT':
            knob = nuke.Int_Knob(k)
            knob.setDefaultValue([default_value])
            knob.setTooltip(tooltip)

        elif _class == 'FLOAT':
            min_value = info.get('min', 0)
            max_value = info.get('max', 1)

            knob = nuke.Double_Knob(k)
            knob.setRange(min_value, max_value)
            knob.setDefaultValue([default_value])
            knob.setTooltip(tooltip)

        elif _class == 'STRING':
            multiline = info.get('multiline', False)

            if multiline:
                knob = nuke.Multiline_Eval_String_Knob(k)
            else:
                knob = nuke.String_Knob(k)

            knob.setTooltip(tooltip)

        elif type(_class) == list:
            knob = nuke.Enumeration_Knob(k, k, _class)
            knob.setTooltip(tooltip)

        else:
            continue

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
