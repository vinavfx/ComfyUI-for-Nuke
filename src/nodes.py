# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import json
import os
import shutil
import random
import traceback
import nuke  # type: ignore

from ..python_util.util import jwrite, jread
from ..nuke_util.nuke_util import get_connected_nodes, get_project_name, get_input

from .common import image_inputs, mask_inputs, get_comfyui_dir, state_dir


def extract_data():
    queue_prompt_node = nuke.thisNode()
    output_node = get_input(queue_prompt_node, 0)

    if not output_node:
        nuke.message('QueuePrompt is not connected!')
        return {}, None

    output_node_data = get_node_data(output_node)
    if not output_node_data.get('output_node', False):
        nuke.message(
            'Connect only to output nodes like SaveImage or SaveEXR !')
        return {}, None

    nodes = get_connected_comfyui_nodes(queue_prompt_node)
    nuke.root().knob('proxy').setValue(False)

    comfyui_nodes = [n.name() for n, _ in nodes]
    data = {}
    input_node_changed = False

    for n, node_data in nodes:
        if not check_node(n):
            return {}, None

        if n.knob('fixed_seed'):
            if not n.knob('fixed_seed').value():
                random_value = random.randrange(1, 9999)

                seed_knob = n.knob('seed_')
                if not seed_knob:
                    seed_knob = n.knob('noise_seed_')

                if seed_knob:
                    seed_knob.setValue(random_value)
                    node_data['inputs'][seed_knob.name()[:-1]] = random_value

        for key in image_inputs + mask_inputs:
            input_key = node_data['inputs'].get(key)
            input_node = nuke.toNode(input_key[0]) if input_key else None

            if not input_node:
                continue

            if not input_node.name() in comfyui_nodes:
                load_image_data, changed_node, execution_canceled = create_load_images_and_save(
                    input_node, key in mask_inputs)

                if execution_canceled:
                    return {}, None

                input_node_changed = True if changed_node else input_node_changed
                data[input_node.name()] = load_image_data

        data[n.name()] = node_data

    return data, input_node_changed


def create_load_images_and_save(node, alpha):
    # State : verifica si las entradas del nodo se modificaron para determinar si reescribir
    state_file = '{}/comfyui_{}_{}_state.json'.format(
        state_dir, get_project_name(), node.name())

    connected_nodes = get_connected_nodes(node, continue_at_up_level=True)
    connected_nodes.append(node)
    state = ''

    for n in connected_nodes:
        n.setSelected(False)
        node_state = ''.join(k.toScript() for k in n.knobs().values())
        node_state = node_state.replace(
            str(n.xpos()), '').replace(str(n.ypos()), '')
        state += node_state

    current_state = {'connected_nodes': state.strip(), 'state_id': 0}

    try:
        prev_state = jread(state_file)
    except:
        prev_state = {}

    load_image_data = {
        'inputs': {
            'filepath': '',
            'linear_to_sRGB': True,
            'image_load_cap': 0,
            'select_every_nth': 1,
            'skip_first_images': 0
        },
        'class_type': 'LoadEXR'
    }

    input_dir = '{}/input'.format(get_comfyui_dir())

    if current_state.get('connected_nodes') == prev_state.get('connected_nodes'):
        dirname = prev_state.get('dirname', 'none')
        sequence_dir = os.path.join(input_dir, dirname)

        if os.path.isdir(sequence_dir):
            files = os.listdir(sequence_dir)
            if files:
                load_image_data['inputs']['filepath'] = sequence_dir
                load_image_data['inputs']['id'] = prev_state.get('state_id', 0)
                return load_image_data, False, False

    dirname = '{}_{}'.format(get_project_name(), node.fullName())
    sequence_dir = os.path.join(input_dir, dirname)
    sequence_dir = sequence_dir.replace('\\', '/')

    if os.path.isdir(sequence_dir):
        shutil.rmtree(sequence_dir)

    os.mkdir(sequence_dir)
    filename = '{}/{}_#####.exr'.format(sequence_dir, dirname)

    # el write se crea dentro de SaveImage
    [n.setSelected(False) for n in nuke.selectedNodes()]

    # Stable Diffusion reconoce las mascaras al reves asi que se invierten
    invert = None
    if alpha:
        invert = nuke.createNode('Invert', inpanel=False)
        invert.setXYpos(node.xpos(), node.ypos())
        invert.setInput(0, node)

    write = nuke.createNode('Write', inpanel=False)
    write.knob('hide_input').setValue(True)
    write.setName(node.name() + '_write')
    write.setXYpos(node.xpos(), node.ypos())
    write.setSelected(False)
    write.setInput(0, invert if invert else node)
    write.knob('file').setValue(filename)
    write.knob('raw').setValue(True)
    write.knob('file_type').setValue('exr')
    write.knob('channels').setValue('rgba' if alpha else 'rgb')

    try:
        nuke.execute(write, node.firstFrame(), node.lastFrame())
    except:
        nuke.delete(invert)
        nuke.delete(write)
        nuke.message(traceback.format_exc())
        return {}, False, True

    nuke.delete(invert)
    nuke.delete(write)

    state_id = random.randrange(1, 9999)
    current_state['dirname'] = dirname
    current_state['state_id'] = state_id

    jwrite(state_file, current_state)

    load_image_data['inputs']['filepath'] = sequence_dir
    load_image_data['inputs']['id'] = state_id

    return load_image_data, True, False


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

        if not inode_data:
            if input_name in image_inputs + mask_inputs:
                if inode.bbox().w() < 10 or inode.bbox().h() < 10:
                    nuke.message(
                        '{}: input "{}" without image !'.format(node.name(), input_name))
                    return
                continue

            else:
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
