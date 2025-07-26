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
from collections import Counter
import nuke  # type: ignore
from ..settings import USE_EXR_TO_LOAD_IMAGES
from ..testing.testing import status_diff

from ..nuke_util.nuke_util import get_connected_nodes, get_project_name
from .common import image_inputs, mask_inputs, get_comfyui_dir

states = {}


def extract_data(frame, run_node):
    output_node = get_input(run_node, 0)

    if not output_node:
        nuke.message('Run is not connected!')
        return {}, None

    output_node_data = get_node_data(output_node)
    if not output_node_data.get('output_node', False):
        nuke.message(
            'Connect only to output nodes like SaveImage or SaveEXR !')
        return {}, None

    nodes = get_connected_comfyui_nodes(run_node, frame=frame)
    nuke.root().knob('proxy').setValue(False)

    from .read_media import get_tonemap
    tonemap = get_tonemap(run_node)

    comfyui_nodes = [n.name() for n, _ in nodes]
    data = {}
    input_node_changed = False

    for n, node_data in nodes:
        if not check_node(n):
            return {}, None

        if n.knob('randomize'):
            if n.knob('randomize').value():
                random_value = random.randrange(1, 9999)

                seed_knob = n.knob('seed_')
                if not seed_knob:
                    seed_knob = n.knob('noise_seed_')

                if seed_knob:
                    seed_knob.setValue(random_value)
                    node_data['inputs'][seed_knob.name()[:-1]] = random_value

        for key in image_inputs + mask_inputs:
            input_key = node_data['inputs'].get(key)
            if not input_key or not type(input_key) == list:
                continue

            input_fullname = '{}.{}'.format(
                n.parent().fullName(), input_key[0])

            if not input_fullname.startswith('root.'):
                input_fullname = 'root.' + input_fullname

            input_node = nuke.toNode(input_fullname) if input_key else None

            if not input_node:
                continue

            if is_switch_any(input_node):
                continue

            if not input_node.name() in comfyui_nodes:
                load_image_data, changed_node, execution_canceled = create_load_images_and_save(
                    input_node, tonemap, frame)

                if execution_canceled:
                    return {}, None

                input_node_changed = True if changed_node else input_node_changed
                data[input_node.name()] = load_image_data

        data[n.name()] = node_data

    return data, input_node_changed


def create_load_images_and_save(node, tonemap, frame=-1):
    animation = frame >= 0

    global states
    connected_nodes = get_connected_nodes(node, continue_at_up_level=True)
    connected_nodes.append(node)
    state = ''

    for n in connected_nodes:
        n.setSelected(False)
        node_state = ''

        # knobs that may vary
        knobs_ignore = ['old_message', 'old_expression_markers']

        for k in n.knobs().values():
            if not k.visible() or not k.enabled():
                continue

            if k.name() in knobs_ignore:
                continue

            if k.hasExpression() or k.isAnimated():
                try:
                    value = k.valueAt(0)
                except:
                    value = k.toScript()
            else:
                value = k.toScript()

            node_state += '{} '.format(value)

        node_state = node_state.replace(
            str(n.xpos()), '').replace(str(n.ypos()), '')

        state += node_state

    current_state = {'connected_nodes': state.strip(), 'state_id': 0}
    prev_state = states.get(node.fullName(), {})

    if USE_EXR_TO_LOAD_IMAGES:
        filepath_key = 'filepath'
        load_image_data = {
            'inputs': {
                'filepath': '',
                'tonemap': tonemap,
                'image_load_cap': 0,
                'select_every_nth': 1,
                'skip_first_images': 0
            },
            'class_type': 'LoadEXR'
        }
    else:
        filepath_key = 'directory'
        load_image_data  = {
            'inputs': {
                'directory': '',
                'skip_first_images': 0,
                'select_every_nth': 1,
                'image_load_cap': 0
            },
            'class_type': 'VHS_LoadImages'
        }

    input_dir = '{}/input'.format(get_comfyui_dir())

    if current_state.get('connected_nodes') == prev_state.get('connected_nodes') and not animation:
        dirname = prev_state.get('dirname', 'none')
        sequence_dir = os.path.join(input_dir, dirname)

        if os.path.isdir(sequence_dir):
            files = os.listdir(sequence_dir)
            if files:
                load_image_data['inputs'][filepath_key] = sequence_dir
                load_image_data['inputs']['id'] = prev_state.get('state_id', 0)
                return load_image_data, False, False

    # For debugging
    #  status_diff(prev_state.get('connected_nodes'),
                #  current_state.get('connected_nodes'))

    dirname = '{}_{}'.format(get_project_name(), node.fullName())
    sequence_dir = os.path.join(input_dir, dirname)
    sequence_dir = sequence_dir.replace('\\', '/')

    if os.path.isdir(sequence_dir):
        shutil.rmtree(sequence_dir)

    os.mkdir(sequence_dir)
    ext = 'exr' if USE_EXR_TO_LOAD_IMAGES else 'png'
    filename = '{}/{}_#####.{}'.format(sequence_dir, dirname, ext)

    [n.setSelected(False) for n in nuke.selectedNodes()]

    onode = node
    invert = None
    if not USE_EXR_TO_LOAD_IMAGES:
        # VHS_LoadImages inverts the alpha
        invert = nuke.createNode('Invert', inpanel=False)
        invert.knob('channels').setValue('alpha')
        invert.setInput(0, node)
        invert.setXYpos(node.xpos(), node.ypos())
        onode = invert

    write = nuke.createNode('Write', inpanel=False)
    write.knob('hide_input').setValue(True)
    write.setName(node.name() + '_write')
    write.setXYpos(node.xpos(), node.ypos())
    write.setSelected(False)
    write.setInput(0, onode)
    write.knob('file').setValue(filename)
    write.knob('raw').setValue(USE_EXR_TO_LOAD_IMAGES)
    write.knob('colorspace').setValue('linear' if USE_EXR_TO_LOAD_IMAGES else 'sRGB')
    write.knob('file_type').setValue(ext)
    write.knob('channels').setValue('rgba')

    try:
        if animation:
            nuke.execute(write, frame, frame)
        else:
            nuke.execute(write, node.firstFrame(), node.lastFrame())
    except:
        nuke.delete(write)
        nuke.delete(invert)
        nuke.message(traceback.format_exc())
        return {}, False, True

    nuke.delete(write)
    nuke.delete(invert)

    state_id = random.randrange(1, 9999)
    current_state['dirname'] = dirname
    current_state['state_id'] = state_id

    states[node.fullName()] = current_state

    load_image_data['inputs'][filepath_key] = sequence_dir
    load_image_data['inputs']['id'] = state_id

    return load_image_data, True, False


def get_connected_comfyui_nodes(root_node, visited=None, ignore_nodes=[], frame=-1):
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

        if is_switch_any(root_node):
            if not root_node.knob('which').value() == i:
                continue

        if inode in visited:
            continue

        node_data = extract_node_data(inode, frame)
        if node_data:
            if node_data['class_type'] in ignore_nodes:
                continue

        visited.add(inode)

        if not is_disabled(inode) and node_data:
            sd_nodes.append((inode, node_data))

        sd_nodes.extend(get_connected_comfyui_nodes(
            inode, visited, ignore_nodes, frame))

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


def extract_node_data(node, frame=-1):
    data = get_node_data(node)
    if not data:
        return {}

    inputs = {}

    for knob in node.knobs().values():
        if not knob.name()[-1:] == '_':
            continue

        if hasattr(knob, 'valueAt') and frame >= 0:
            value = knob.valueAt(frame) if knob.isAnimated() else knob.value()
        else:
            value = knob.value()

        if type(knob) == nuke.Enumeration_Knob:
            try:
                value = float(value)
            except:
                pass

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
        output_index = 0

        if not get_node_data(inode):
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

    force_output = node_data['inputs'][input_index].get('force_output')
    if not force_output == None:
        return force_output

    for allowed_output in allowed_outputs:
        for i, o in enumerate(inode_outputs):
            if allowed_output in [o, '*'] or '*' == o:
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
        _input = node_data['inputs'][i]
        allowed_outputs = _input['outputs']

        if '*' not in allowed_outputs and '*' not in inode_outputs:
            if not any(o in allowed_outputs for o in inode_outputs):
                nuke.message(
                    node.name() + ' : "{}" connection not supported !'.format(input_name))
                return

        if requires_force_output(inode_outputs, allowed_outputs[0]):
            if _input.get('force_output') == None:
                if nuke.ask('{}:\nConnected to node with duplicate outputs, Connect now?'.format(node.name())):
                    from .scripts.force_output_connection import force_output
                    force_output(node)
                return

    return True


def requires_force_output(outputs, input_class):
    contador = Counter(outputs)
    repeated = [item for item, count in contador.items() if count > 1]

    if input_class == '*' and len(outputs) > 1:
        pass
    else:
        if not repeated:
            return False

        if not '*' in repeated:
            if not input_class in repeated:
                return False

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


def is_switch_any(node):
    if not node.Class() == 'Switch':
        return

    if not node.knob('switch_any'):
        return

    return True


def get_input(node, i, ignore_disabled=True):
    if not node:
        return

    inode = node.input(i)

    for _ in range(100):
        if not inode:
            return

        disable_knob = inode.knob('disable')
        disabled_node = False

        if disable_knob and ignore_disabled:
            disabled_node = inode.knob('disable').value()

        if inode.Class() == 'Dot' or disabled_node:
            if inode.input(0):
                inode = inode.input(0)
                continue
            else:
                return

        if is_switch_any(inode):
            which = int(inode.knob('which').value())
            if inode.input(which):
                inode = inode.input(which)
                continue
            else:
                return

        return inode
