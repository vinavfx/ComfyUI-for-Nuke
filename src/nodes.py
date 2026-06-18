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

from ..nuke_util.nuke_util import get_connected_nodes, get_project_name
from .common import (image_inputs, mask_inputs, get_name_code, show_message, jsondumps, jsonloads)

states = {}


def extract_data(run_node, settings):
    output_node = get_input(run_node, 0)

    if not output_node:
        show_message('Run is not connected!')
        return {}, None

    output_node_data = get_node_data(output_node)
    if not output_node_data.get('output_node', False):
        show_message('Connect only to output nodes like SaveImage or SaveEXR !')
        return {}, None

    nodes = get_connected_comfyui_nodes(run_node)
    nuke.root().knob('proxy').setValue(False)

    comfyui_nodes = [n.name() for n, _ in nodes]
    data = {}
    input_node_changed = False
    rendered_nodes = set()

    for n, node_data in nodes:
        if not check_node(n):
            return {}, None

        if n.knob('randomize'):
            if n.knob('randomize').value():
                random_value = random.randrange(1, 9999)

                seed_knob = next((n.knob(k) for k in (
                    'seed_', 'noise_seed_', 'value_') if n.knob(k)), None)

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

            with nuke.Root():
                input_node = nuke.toNode(input_fullname) if input_key else None

            run_node.begin()

            if not input_node:
                continue

            if is_switch_any(input_node):
                continue

            if is_null_input(input_node):
                continue

            if not input_node.name() in comfyui_nodes:
                load_image_data, changed_node, execution_canceled = create_load_images_and_save(
                    input_node, settings, rendered_nodes)

                if execution_canceled:
                    return {}, None

                # nuke_attrs used in "copy_workflow"
                load_image_data['nuke_attrs'] = {
                    'xpos': input_node.xpos(),
                    'ypos': input_node.ypos(),
                    'tile_color': input_node['tile_color'].value()
                }

                input_node_changed = True if changed_node else input_node_changed
                data[input_node.name()] = load_image_data

        # nuke_attrs used in "copy_workflow"
        node_data['nuke_attrs'] = {
            'xpos': n.xpos(),
            'ypos': n.ypos(),
            'tile_color': n['tile_color'].value()
        }
        data[n.name()] = node_data

    return data, input_node_changed


def state_node(node):
    connected_nodes = get_connected_nodes(node, continue_at_up_level=True)
    connected_nodes = [n for n in connected_nodes if not n.Class() == 'Dot']
    connected_nodes.append(node)
    state = ''

    ct = nuke.nodes.CurveTool(
        inputs=[node], operation='Avg Intensities', channels='rgba')
    ct['ROI'].setValue([0, 0, node.width(), node.height()])
    nuke.execute(ct, node.firstFrame(), node.firstFrame())
    rgba = [round(v, 5) for v in ct['intensitydata'].value()]
    nuke.delete(ct)

    attrs = [
        rgba,
        len(connected_nodes),
        node.firstFrame(),
        node.lastFrame(),
        node.width(),
        node.height(),
        node.bbox().x(),
        node.bbox().y(),
        node.bbox().w(),
        node.bbox().h(),
    ]

    state += ','.join([str(i) for i in attrs])
    knobs_analyze = ['disable', 'name']

    for n in connected_nodes:
        knobs_state = ''

        for k in n.knobs().values():
            if not k.visible() or not k.enabled():
                continue

            if not k.name() in knobs_analyze:
                continue

            if k.hasExpression() or k.isAnimated():
                try:
                    value = k.valueAt(0)
                except:
                    value = k.toScript()
            else:
                value = k.toScript()

            knobs_state += '{} '.format(value)

        state += knobs_state

    return state


def create_load_images_and_save(node, settings, rendered_nodes):
    global states
    state = state_node(node)

    current_state = {'connected_nodes': state.strip(), 'state_id': 0}
    prev_state = states.get(node.fullName(), {})

    frame_range = [node.firstFrame(), node.lastFrame()]
    USE_EXR_TO_LOAD_IMAGES = settings['USE_EXR_TO_LOAD_IMAGES']

    if USE_EXR_TO_LOAD_IMAGES:
        filepath_key = 'filepath'
        load_image_data = {
            'frame_range': frame_range,
            'inputs': {
                'filepath': '',
                'tonemap': 'linear',
                'image_load_cap': 0,
                'skip_first_images': 0,
                'select_every_nth': 1
            },
            'class_type': 'LoadEXR'
        }
    else:
        filepath_key = 'directory'
        load_image_data  = {
            'frame_range': frame_range,
            'inputs': {
                'directory': '',
                'image_load_cap': 0,
                'skip_first_images': 0,
                'select_every_nth': 1
            },
            'class_type': 'VHS_LoadImagesPath'
        }

    if current_state.get('connected_nodes') == prev_state.get('connected_nodes') or node in rendered_nodes:
        sequence_dir = prev_state.get('sequence_dir', 'none')
        filepath = prev_state.get('filepath', 'none')
        same_exr_setting = prev_state.get(
            'USE_EXR_TO_LOAD_IMAGES') == USE_EXR_TO_LOAD_IMAGES

        if os.path.isdir(sequence_dir) and os.listdir(sequence_dir) and same_exr_setting:
            load_image_data['inputs'][filepath_key] = filepath
            load_image_data['inputs']['id'] = prev_state.get('state_id', 0)
            return load_image_data, False, False

    dirname = get_name_code('{}{}{}{}'.format(
        get_project_name(), node.fullName(), frame_range[0], frame_range[1]))

    sequence_dir = os.path.join(settings['INPUT_DIRECTORY'], dirname)
    filepath = sequence_dir

    if os.path.isdir(sequence_dir):
        shutil.rmtree(sequence_dir)

    os.makedirs(sequence_dir)
    ext = 'exr' if USE_EXR_TO_LOAD_IMAGES else 'tiff'
    filename = '{}/{}_#####.{}'.format(sequence_dir, dirname, ext)

    [n.setSelected(False) for n in nuke.selectedNodes()]

    invert = nuke.createNode('Invert', inpanel=False)
    invert.knob('channels').setValue('alpha')
    invert.setInput(0, node)
    invert.setXYpos(node.xpos(), node.ypos())

    # VHS_LoadImages inverts the alpha
    if USE_EXR_TO_LOAD_IMAGES:
        invert['disable'].setValue(True)

    crop = nuke.createNode('Crop', inpanel=False)
    crop.knob('box').setValue([0, 0, node.width(), node.height()])
    crop.setInput(0, invert)
    crop.setXYpos(node.xpos(), node.ypos())

    clamp = nuke.createNode('Clamp', inpanel=False)
    clamp.setInput(0, crop)

    ocio_display = nuke.createNode('OCIODisplay', inpanel=False)
    ocio_display['disable'].setValue(True)
    ocio_display.setInput(0, clamp)

    write = nuke.createNode('Write', inpanel=False)
    write.knob('hide_input').setValue(True)
    write.setName(node.name() + '_write')
    write.setXYpos(node.xpos(), node.ypos())
    write.setSelected(False)
    write.setInput(0, ocio_display)
    write.knob('file').setValue(filename)
    write.knob('file_type').setValue(ext)
    write.knob('channels').setValue('rgba')

    if USE_EXR_TO_LOAD_IMAGES:
        if nuke.Root()['colorManagement'].value() == 'OCIO':
            ocio_view = ocio_display['view'].values()

            if 'Un-tone-mapped' in ocio_view:
                ocio_display['disable'].setValue(False)
                ocio_display['view'].setValue('Un-tone-mapped')
            else:
                write['colorspace'].setValue('matte_paint')
        else:
            write['colorspace'].setValue('sRGB')

    def clean():
        nuke.delete(write)
        nuke.delete(invert)
        nuke.delete(crop)
        nuke.delete(clamp)
        nuke.delete(ocio_display)

    try:
        nuke.execute(write, node.firstFrame(), node.lastFrame())
    except:
        clean()
        show_message(traceback.format_exc())
        return {}, False, True

    clean()

    state_id = random.randrange(1, 9999)
    current_state['sequence_dir'] = sequence_dir
    current_state['filepath'] = filepath
    current_state['USE_EXR_TO_LOAD_IMAGES'] = USE_EXR_TO_LOAD_IMAGES
    current_state['state_id'] = state_id

    states[node.fullName()] = current_state
    rendered_nodes.add(node)

    load_image_data['inputs'][filepath_key] = filepath
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

        if is_switch_any(root_node):
            if not root_node.knob('which').value() == i:
                continue

        if is_null_input(root_node):
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

    data = jsonloads(data_knob.value())
    if data:
        return data

    # Codigo para nodos viejos, borrar mas adelante!
    value = data_knob.value()
    if not 'class_type' in value:
        return {}

    data = value.split('#')[0].replace("'", '"').replace(
        'True', 'true').replace('False', 'false')
    return json.loads(data)



def save_node_data(node, data):
    node.knob('data').setValue(jsondumps(data))


def extract_node_data(node):
    data = get_node_data(node)
    if not data:
        return {}

    inputs = {}

    for knob in node.knobs().values():
        if not knob.name()[-1:] == '_':
            continue

        if hasattr(knob, 'valueAt'):
            value = knob.valueAt(1) if knob.isAnimated() and not knob.hasExpression() else knob.value()
        else:
            value = knob.value()

        if type(knob) == nuke.Enumeration_Knob:
            try:
                value = float(value)
            except:
                pass

        elif type(knob) == nuke.Multiline_Eval_String_Knob:
            value = knob.toScript()

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
            show_message(
                node.name() + ' : "{}" input disconnected !'.format(input_name))
            return

        inode_data = get_node_data(inode)

        if not inode_data:
            if input_name in image_inputs + mask_inputs:
                if inode.bbox().w() < 10 or inode.bbox().h() < 10:
                    show_message(
                        '{}: input "{}" not connected or bbox without information in some frame !'.format(node.name(), input_name))
                    return
                continue

            else:
                show_message('{}: "{}" does not support "{}" !'.format(
                    node.name(), input_name, inode.name()))
                return

        inode_outputs = inode_data['outputs']
        _input = node_data['inputs'][i]
        allowed_outputs = _input['outputs']

        if '*' not in allowed_outputs and '*' not in inode_outputs:
            if not any(o in allowed_outputs for o in inode_outputs):
                show_message(
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


def is_null_input(node):
    if not node.Class() == 'Group':
        return

    if not node.knob('null_input'):
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

        if inode.Class() == 'Dot' or disabled_node or inode.knob('override_settings'):
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

        if is_null_input(inode):
            return

        return inode
