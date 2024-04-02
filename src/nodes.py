# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import json
import nuke  # type: ignore
from ..nuke_util.nuke_util import get_input

from .common import image_inputs, mask_inputs


def get_connected_comfyui_nodes(root_node, visited=None, ignore_nodes=[]):
    if visited is None:
        visited = set()

    def is_disabled(n):
        disable_knob = n.knob('disable')
        if not disable_knob:
            return

        if disable_knob.value():
            return True

    sd_nodes = []

    for i in range(root_node.maxInputs()):
        inode = root_node.input(i)

        if not inode:
            continue

        if not i == 0 and is_disabled(root_node):
            continue

        if inode in visited:
            continue

        node_data = extract_node_data(inode)
        if node_data:
            if node_data['class_type'] in ignore_nodes:
                continue

        visited.add(inode)

        if not is_disabled(inode) and node_data:
            sd_nodes.append((inode, node_data))

        sd_nodes.extend(get_connected_comfyui_nodes(
            inode, visited, ignore_nodes))

    return sd_nodes


def get_node_data(node):
    data_knob = node.knob('data')

    if not data_knob:
        return {}

    value = data_knob.value()
    if not 'class_type' in value:
        return {}

    data = value.split('#')[0].replace("'", '"').replace(
        'True', 'true').replace('False', 'false')
    return json.loads(data)


def extract_node_data(node):
    data = get_node_data(node)
    if not data:
        return {}

    inputs = {}

    for knob in node.knobs().values():
        if not knob.name()[-1:] == '_':
            continue

        value = knob.value()
        if type(value) in [float, int]:
            value = int(value) if int(value) == value else value

        name = knob.name()[:-1]
        inputs[name] = value

    for i in range(node.maxInputs()):
        inode = get_input(node, i)

        if not inode:
            continue

        ignore = data['inputs'][i].get('ignore', False)
        if ignore:
            continue

        input_name = data['inputs'][i]['name']

        if input_name in image_inputs:
            output_index = 0
        elif input_name in mask_inputs:
            output_index = 1
        else:
            output_index = get_output_index(node, data, i)
            if output_index == -2:
                continue

        if input_name in inputs:
            continue

        inputs[input_name] = [inode.name(), output_index]

    return {'inputs': inputs, 'class_type': data['class_type']}


def get_output_index(node, node_data, input_index):
    inode_data = get_node_data(get_input(node, input_index))
    if not inode_data:
        return -2

    inode_outputs = inode_data['outputs']

    allowed_outputs = node_data['inputs'][input_index]['outputs']

    for allowed_output in allowed_outputs:
        for i, o in enumerate(inode_outputs):
            if allowed_output == o:
                return i

    return -1


def check_node(node):
    node_data = get_node_data(node)

    for i in range(node.maxInputs()):
        inode = get_input(node, i)

        index_data = node_data['inputs'][i]
        input_name = index_data['name']
        optional_input = index_data.get('opt', False)

        if optional_input and not inode:
            continue

        if not inode:
            nuke.message(
                node.name() + ' : "{}" input disconnected !'.format(input_name))
            return

        inode_data = get_node_data(inode)

        if input_name in image_inputs + mask_inputs:
            if inode_data and inode_data.get('class_type') == 'SaveImage':
                continue
            else:
                if inode.bbox().w() < 10 or inode.bbox().h() < 10:
                    nuke.message(
                        'input "{}" without image !'.format(input_name))
                    return
                continue

        if not inode_data:
            nuke.message('{}: "{}" does not support "{}" !'.format(
                node.name(), input_name, inode.name()))
            return

        inode_outputs = inode_data['outputs']
        allowed_outputs = node_data['inputs'][i]['outputs']

        if not any(o in allowed_outputs for o in inode_outputs):
            nuke.message(
                node.name() + ' : "{}" connection not supported !'.format(input_name))
            return

    return True


def update_input_nodes(node):
    for n in nuke.allNodes():
        if n.Class() == 'Input':
            nuke.delete(n)

    data = get_node_data(node)

    for idx, i in enumerate(data['inputs']):
        inode = nuke.createNode('Input', inpanel=False)
        inode.setName(i['name'])

        if idx == 0:
            nuke.toNode('Output1').setInput(0, inode)
