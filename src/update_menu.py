# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from functools import partial
from collections import OrderedDict
import re
import os
import json
import nuke  # type: ignore

from ..nuke_util.nuke_util import set_tile_color, get_output_nodes
from .connection import GET, convert_to_utf8
from .queue_prompt import error_node_style
from ..env import NUKE_USER

path = os.path.join(NUKE_USER, 'nuke_comfyui')
comfyui_nodes = {}
menu_updated = False


def remove_signs(string):
    return re.sub(r'[^a-zA-Z0-9_]', '', string)


def create_comfyui_node(attrs, inpanel=True):
    node_type = attrs["type"]
    node_data = comfyui_nodes.get(node_type)
    if not node_data:
        return

    return create_node(node_data, attrs, inpanel)


def create_node(data, attrs=None, inpanel=True):
    try:
        selected_node = nuke.selectedNode()
    except:
        selected_node = None

    n = nuke.createNode('Group', inpanel=inpanel)

    name = remove_signs(data['name'])
    display_name = remove_signs(data['display_name'])
    if display_name[0].isdigit():
        display_name = '_' + display_name

    n.setName(display_name)

    category = data['category'].split('/')[-1]

    if category == 'loaders':
        set_tile_color(n, [.57, .58, .48])
    elif category == 'mask':
        set_tile_color(n, [.33, .42, .77])
    elif 'VAE' in name:
        set_tile_color(n, [.08, .8, .97])
    elif 'Save' in name:
        set_tile_color(n, [.16, 1, .74])
    elif 'Merge' in name or 'Combine' in name:
        set_tile_color(n, [.64, .62, .77])

    inputs = []

    input_data = data['input']
    required = input_data.get('required', {})
    optional = input_data.get('optional', {})

    input_order = data.get('input_order', {})
    required_order = input_order.get('required', [])
    optional_order = input_order.get('optional', [])

    knobs_order = []

    if attrs:
        '''
        Here we convert the Primitive node placeholder into py compatible 
        nodes (COMBO is not supported and will baked into the original node)
        This requires 'CR Seed' 'Easy Use' custom nodes
        '''
        if attrs.get('type', '') == 'PrimitiveNode':
            if attrs['outputs'][0]['type'].lower() == "int":
                data['name'] = 'CR Seed'
                knob = nuke.Int_Knob(attrs['outputs'][0]['widget']['name'] + '_', attrs['outputs'][0]['widget']['name'])
                default_value = attrs['widgets_values'][0]
                default_value = default_value if default_value < 1e9 else 1e9
                default_value = int(default_value)
                knob.setValue(default_value)
                n.addKnob(knob)
                knobs_order.append(knob.name())
                
                randomize_knob = nuke.Boolean_Knob('randomize')
                randomize_knob.setTooltip(
                    'Allows the linked QueuePrompt to automatically change the seed by randomizing the number.')
                randomize_knob.setValue(True if attrs['widgets_values'][1] == 'fixed' else False)
                n.addKnob(randomize_knob)

            if attrs['outputs'][0]['type'].lower() == "float":
                data['name'] = 'easy float'
                knob = nuke.Double_Knob(attrs['outputs'][0]['widget']['name'] + '_', attrs['outputs'][0]['widget']['name'])
                knob.clearFlag(0x0000000000000002)
                default_value = attrs['widgets_values'][0]
                default_value = int(default_value)
                knob.setValue(default_value)
                n.addKnob(knob)
                knobs_order.append(knob.name())

            if attrs['outputs'][0]['type'].lower() == "string":
                data['name'] = 'easy string'
                knob = nuke.Multiline_Eval_String_Knob(attrs['outputs'][0]['widget']['name'] + '_', attrs['outputs'][0]['widget']['name'])
                default_value = attrs['widgets_values'][0]
                default_value = str(default_value)
                knob.setValue(default_value)
                n.addKnob(knob)
                knobs_order.append(knob.name())

            if attrs['outputs'][0]['type'].lower() == "combo":
                data['name'] = 'NOTSUPPORTED'
                default_value = attrs['widgets_values'][0]
                default_value = str(default_value)
                knob = knob = nuke.Enumeration_Knob(attrs['outputs'][0]['widget']['name'] + '_', attrs['outputs'][0]['widget']['name'], [default_value])
                error_node_style(n.fullName(), True, 'Not supported PrimitiveNode alternatives for COMBO!')
                n.addKnob(knob)
                knobs_order.append(knob.name())

    for key in required_order + optional_order:
        _input = required.get(key, [])
        is_optional = not _input

        if is_optional:
            _input = optional.get(key)

        _class = _input[0]
        info = _input[1] if len(_input) == 2 else {}

        if not type(info) == dict:
            continue

        tooltip = info.get('tooltip', '')
        placeholder = info.get('placeholder', '')
        force_input = info.get('forceInput', False)
        default_value = info.get('default', 0)

        knob_name = key + '_'

        def is_default_widget()->bool:
            '''
            this will check if the widget is converted to input so we can skip internal knob creation
            '''
            if attrs:
                for i in attrs.get('inputs', []):
                    if i['name'].lower() == key:
                        if _class == i['type']:
                            skip_list = attrs.get('skip_knobs', [])
                            skip_list.append(knob_name)
                            return False
            return True

        if force_input:
            inputs.append([key, _class, is_optional])
            continue

        elif _class == 'INT':
            knob = nuke.Int_Knob(knob_name, key)
            default_value = default_value if default_value < 1e9 else 1e9
            knob.setValue(int(default_value))
            knob.setTooltip(tooltip)

        elif _class == 'FLOAT':
            min_value = info.get('min', 0)
            max_value = info.get('max', 1)

            knob = nuke.Double_Knob(knob_name, key)
            knob.setRange(min_value, max_value)
            knob.setValue(default_value)
            knob.setTooltip(tooltip)

        elif _class == 'STRING' and key in ['filepath', 'file', 'directory', 'output_directory']:
            knob = nuke.File_Knob(knob_name, key)
            knob.setTooltip(tooltip)

        elif _class == 'STRING':
            multiline = info.get('multiline', False)

            if multiline:
                knob = nuke.Multiline_Eval_String_Knob(knob_name, key)
            else:
                knob = nuke.String_Knob(knob_name, key)

            default_string = info.get('default', '')
            knob.setText(str(default_string))
            knob.setTooltip(tooltip + placeholder)

        elif _class in ['BOOLEAN', [True, False], [[True, False]]]:
            knob = nuke.Boolean_Knob(knob_name, key)
            knob.setFlag(nuke.STARTLINE)
            knob.setValue(default_value)
            knob.setTooltip(tooltip)

        elif type(_class) == list: # since COMBO is not supported by primitive alternatives we leave it in the node
            knob = nuke.Enumeration_Knob(
                knob_name, key, [str(i) for i in _class])

            knob.setTooltip(tooltip)
            default_item = str(info.get('default', None))

            if not default_item == 'None':
                knob.setValue(default_item)

        else:
            if attrs == None:
                inputs.append([key, _class, is_optional])
            continue
        
        if not is_default_widget():
            '''Setting the knob to disabled state to not get parsed during extraction data in nodes.py'''
            knob.setVisible(False)
            knob.setEnabled(False)

        n.addKnob(knob)
        knobs_order.append(knob.name())

        if name in ['LoadAudio', 'LoadImage']:
            upload_knob = nuke.PyScript_Knob('upload', '+')
            upload_knob.setValue('comfyui.upload.upload_media()')
            n.addKnob(upload_knob)

        if 'seed' in key and is_default_widget():
            randomize_knob = nuke.Boolean_Knob('randomize')
            randomize_knob.setTooltip(
                'Allows the linked QueuePrompt to automatically change the seed by randomizing the number.')
            randomize_knob.setValue(False)
            n.addKnob(randomize_knob)

    # Nuke no genera automaticamente una nueva entrada, asi que genera una entrada 2 cuando solo hay 1 !
    # yuri, I don't understand these two lines below..
    if inputs:
        inputs.append(['input_2'] + inputs[0][1:]
                      ) if inputs[0][0] == 'input_1' else None
        
    if attrs:
        for input in attrs.get('inputs', []):
            inputs.append([input['name'], input['type'].lower(), True])

    _inputs = []

    n.begin()
    for key, _class, is_optional in inputs:
        if not _class:
            continue

        inode = nuke.createNode('Input', inpanel=False)
        inode.setName(remove_signs(key))

        _inputs.append({
            'name': key,
            'outputs': [_class.lower()],
            'opt': is_optional
        })


    nuke.createNode('Output', inpanel=False)
    n.end()

    data_knob = nuke.PyScript_Knob('data')
    data_knob.setVisible(False)

    outputs = []

    if attrs:
        if 'outputs' in attrs:
            for output in attrs['outputs']:
                if type(output) == list:
                    outputs.append(output['name'])
                else:
                    outputs.append(output['type'].lower())
    else:
        for output, output_name in zip(data['output'], data['output_name']):
            if type(output) == list:
                outputs.append(output_name)
            else:
                outputs.append(output.lower()) 

    data_knob.setValue(json.dumps({
        'knobs_order': knobs_order,
        'class_type': data['name'],
        'output_node': data.get('output_node', False),
        'inputs': _inputs,
        'outputs': outputs,
    }, indent=4).replace('"', "'"))

    n.addKnob(data_knob)

    if n.knob('User'):
        n.knob('User').setName('Controls')

    if selected_node:
        n.setXYpos(selected_node.xpos(), selected_node.ypos() + 24)
        n.setInput(0, selected_node)
        for i, onode in get_output_nodes(selected_node):
            onode.setInput(i, n)

    if 'ShowText' in name:
        show_knob = nuke.Multiline_Eval_String_Knob('text', '')
        n.addKnob(show_knob)
        n.knob('text').setFlag(nuke.READ_ONLY)
        n.knob('onCreate').setValue(
            'nuke.thisNode().knob("text").setFlag(nuke.READ_ONLY)')
        output_text_node = nuke.createNode('StickyNote', inpanel=False)
        output_text_node.setName(display_name + 'Output')
        output_text_node.setXYpos(n.xpos() - 100, n.ypos())
        output_text_node.knob('label').setText(
            '[value {}.name]'.format(n.name()))
        n.setSelected(True)

    return n


def update_menu():
    if menu_updated:
        return True

    return update()


def update():
    global menu_updated

    info = GET('object_info')
    if not info:
        return

    menu_updated = True

    comfyui_menu = nuke.menu('Nodes').addMenu('ComfyUI')

    for item in comfyui_menu.items():
        if item.name() in ['Update all ComfyUI', 'Basic Nodes', 'Gizmos']:
            continue

        if not hasattr(item, 'clearMenu'):
            continue
        item.clearMenu()

    load_exr_exist = False
    nodes = {}

    add_js_nodes(info)

    def normalize_string(string):
        string = ''.join(char if ord(
            char) < 128 else '' for char in string)
        return string.replace(' /', '/').replace('/ ', '/').strip()

    for _, value in info.items():
        name = value['name'].replace('+', '')

        if name == 'LoadEXR':
            load_exr_exist = True

        display_name = normalize_string(value['display_name'])
        category = normalize_string(value['category'])

        if not category:
            category = 'Uncategorized'

        value['category'] = category

        item_name = '{}/{}'.format(category, display_name)
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
        value_utf8 = convert_to_utf8(value)

        comfyui_nodes[value['name']] = value_utf8
        comfyui_menu.addCommand(fullname, partial(
            create_node, value_utf8), '', icon_gray)

    return True

def add_js_nodes(info):
    '''
    PrimitiveNode is not in the nodes list due to the fact that is javaScript UI only and doesnt interact with the prompt
    Here we add it to the nodes list so that we can parse it as all the rest of the nodes
    TODO yuri, we need to add all the js nodes for better compatibility
    '''
    primitive_node = """OrderedDict(
            [(
        "PrimitiveNode",
        OrderedDict(
            [
                ("input",OrderedDict([]),),
                ("output", []),
                ("output_is_list", [False]),
                ("output_name", []),
                ("name", "PrimitiveNode"),
                ("display_name", "Primitive"),
                ("description", ""),
                ("python_module", "nodes"),
                ("category", "utils"),
                ("output_node", False),
            ]
        ),
    )])"""
    primitive_node_dict = eval(primitive_node)
    info.update(primitive_node_dict)