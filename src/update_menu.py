# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from functools import partial
import re
import os
import json
import nuke  # type: ignore

from ..nuke_util.nuke_util import set_tile_color
from .connection import GET
from ..env import NUKE_USER

path = os.path.join(NUKE_USER, 'nuke_comfyui')


def create_node(data):
    n = nuke.createNode('Group')

    name = re.sub(r'[^a-zA-Z0-9_]', '', data['name'])
    n.setName(name)

    category = data['category'].split('/')[-1]

    if category == 'loaders':
        set_tile_color(n, [.57, .58, .48])
    elif category == 'mask':
        set_tile_color(n, [.33, .42, .77])
    elif 'VAE' in name:
        set_tile_color(n, [.08, .8, .97])
    elif 'Save' in name:
        set_tile_color(n, [.16, 1, .74])

    inputs = []

    input_data = data['input']
    required = input_data.get('required', {})
    optional = input_data.get('optional', {})

    input_order = data.get('input_order', {})
    required_order = input_order.get('required', [])
    optional_order = input_order.get('optional', [])

    for key in required_order + optional_order:
        _input = required.get(key, [])
        is_optional = not _input

        if is_optional:
            _input = optional.get(key)

        _class = _input[0]
        info = _input[1] if len(_input) == 2 else {}

        tooltip = info.get('tooltip', '')
        default_value = info.get('default', 0)
        force_input = info.get('forceInput', False)

        knob_name = key + '_'

        if force_input:
            inputs.append([key, _class, is_optional])
            continue

        elif _class == 'INT':
            knob = nuke.Int_Knob(knob_name, key)
            knob.setValue(default_value)
            knob.setTooltip(tooltip)

        elif _class == 'FLOAT':
            min_value = info.get('min', 0)
            max_value = info.get('max', 1)

            knob = nuke.Double_Knob(knob_name, key)
            knob.setRange(min_value, max_value)
            knob.setValue(default_value)
            knob.setTooltip(tooltip)

        elif _class == 'STRING' and key in ['filepath', 'file', 'directory']:
            knob = nuke.File_Knob(knob_name, key)
            knob.setTooltip(tooltip)

        elif _class == 'STRING':
            multiline = info.get('multiline', False)

            if multiline:
                knob = nuke.Multiline_Eval_String_Knob(knob_name, key)
            else:
                knob = nuke.String_Knob(knob_name, key)

            default_string = info.get('default', '')
            knob.setText(default_string)
            knob.setTooltip(tooltip)

        elif _class == 'BOOLEAN':
            knob = nuke.Boolean_Knob(knob_name, key)
            knob.setFlag(nuke.STARTLINE)
            knob.setValue(default_value)
            knob.setTooltip(tooltip)

        elif type(_class) == list:
            knob = nuke.Enumeration_Knob(knob_name, key, _class)
            knob.setValue(str(info.get('default', '')))
            knob.setTooltip(tooltip)

        else:
            inputs.append([key, _class, is_optional])
            continue

        n.addKnob(knob)

        if name in ['LoadAudio', 'LoadImage']:
            upload_knob = nuke.PyScript_Knob('upload', '+')
            upload_knob.setValue('comfyui.upload.upload_media()')
            n.addKnob(upload_knob)

        if 'seed' in key:
            fixed_knob = nuke.Boolean_Knob('fixed_seed')
            fixed_knob.setValue(True)
            n.addKnob(fixed_knob)

    _inputs = []

    n.begin()
    for key, _class, is_optional in inputs:
        inode = nuke.createNode('Input', inpanel=False)
        inode.setName(key)

        _inputs.append({
            'name': key,
            'outputs': [_class.lower()],
            'opt': is_optional
        })

    nuke.createNode('Output', inpanel=False)
    n.end()

    data_knob = nuke.PyScript_Knob('data')
    data_knob.setVisible(False)

    data_knob.setValue(json.dumps({
        'class_type': data['name'],
        'output_node': data.get('output_node', False),
        'inputs': _inputs,
        'outputs': [o.lower() for o in data['output']]
    }, indent=4).replace('"', "'"))

    n.addKnob(data_knob)

    if n.knob('User'):
        n.knob('User').setName('Controls')


def update():
    info = GET('object_info')
    if not info:
        return

    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI')

    for item in comfyui_menu.items():
        if item.name() in ['Update all ComfyUI', 'Basic Nodes']:
            continue

        if not hasattr(item, 'clearMenu'):
            continue
        item.clearMenu()

    ignore_nodes = ['EmptyLatentImage']
    load_exr_exist = False
    nodes = {}

    for _, value in info.items():
        name = value['name'].replace('+', '')
        if name in ignore_nodes:
            continue

        if name == 'LoadEXR':
            load_exr_exist = True

        category = value['category']
        category = ''.join(char if ord(
            char) < 128 else '' for char in category)
        category = category.replace(' /', '/').replace('/ ', '/').strip()

        if not category:
            category = 'Uncategorized'

        value['category'] = category

        item_name = '{}/{}'.format(category.strip(), name.strip())
        nodes[item_name] = value

    if not load_exr_exist:
        nuke.message('ComfyUI-HQ-Image-Save module is required !')

    icon_gray = '{}/icons/comfyui_icon_gray.png'.format(path)

    for fullname, value in sorted(nodes.items()):
        input_data = value.get('input', {})
        input_order = value.get('input_order', {})

        if not input_order:
            value['input_order'] = {
                'required': list(input_data.get('required', {})),
                'optional': list(input_data.get('optional', {}))
            }

        value = json.loads(json.dumps(value))  # OrderedDict to Dict

        comfyui_menu.addCommand(fullname, partial(
            create_node, value), '', icon_gray)
