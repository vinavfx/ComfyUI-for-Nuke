# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import uuid
import traceback

import os
import shutil
from time import sleep
import random
import websocket
import json
import threading

from ..nuke_util.nuke_util import get_connected_nodes, get_project_name, get_nuke_path
from ..python_util.util import jwrite, jread
from ..settings import IP, PORT
from .common import get_comfyui_dir, image_inputs, mask_inputs
from .connection import send_request, interrupt
from .nodes import check_node, extract_node_data, get_connected_comfyui_nodes

client_id = str(uuid.uuid4())[:32].replace('-', '')

state_dir = '{}/comfyui_state'.format(get_nuke_path())
if not os.path.isdir(state_dir):
    os.mkdir(state_dir)

if not getattr(nuke, 'comfyui_running', False):
    nuke.comfyui_running = False


def comfyui_submit():
    if nuke.comfyui_running:
        nuke.message('Inference in execution !')
        return

    nuke.comfyui_running = True

    comfyui_dir = get_comfyui_dir()
    if not comfyui_dir:
        nuke.comfyui_running = False
        return

    save_image_node = nuke.thisNode()
    data, input_node_changed = extract_data()

    if not data:
        nuke.comfyui_running = False
        return

    state_file = '{}/comfyui_{}_{}_state.txt'.format(
        state_dir,  get_project_name(), save_image_node.name())

    if os.path.isfile(state_file):
        if data == jread(state_file) and not input_node_changed:
            nuke.message('No new changes !')
            nuke.comfyui_running = False
            return

    jwrite(state_file, data)

    filename_prefix = get_filename_prefix(save_image_node)
    data[save_image_node.name()]['inputs']['filename_prefix'] = filename_prefix

    save_image_node.knob('comfyui_submit').setEnabled(False)

    body = {
        'client_id': client_id,
        'prompt': data,
        'extra_data': {}
    }

    error = send_request('prompt', body)
    if error:
        nuke.comfyui_running = False
        nuke.message(error)
        save_image_node.knob('comfyui_submit').setEnabled(True)
        return

    progress(save_image_node)


def progress(save_image_node):
    url = "ws://{}:{}/ws?clientId={}".format(IP, PORT, client_id)
    task = [nuke.ProgressTask('ComfyUI Connection...')]

    def on_message(_, message):
        message = json.loads(message)

        data = message.get('data', None)
        type_data = message.get('type', None)

        if not data:
            return

        if type_data == 'status':
            queue_remaining = data.get('status', {}).get(
                'exec_info', {}).get('queue_remaining')

            if not queue_remaining and task:
                del task[0]

        elif type_data == 'progress':
            progress = int(data['value'] * 100 / data['max'])
            if task:
                task[0].setProgress(progress)

        elif type_data == 'executing':
            node = data.get('node')

            if node and task:
                task[0].setMessage('Inference: ' + node)

        elif type_data == 'execution_error':
            error = 'Error: {}\n\n'.format(data.get('node_type'))
            error += data.get('exception_message') + '\n\n'

            for tb in data.get('traceback'):
                error += tb + '\n'

            nuke.executeInMainThread(nuke.message, args=(error))

    def on_error(ws, error):
        ws.close()
        if task:
            del task[0]

        if 'connected' in str(error):
            return

        nuke.executeInMainThread(nuke.message, args=('error: ' + str(error)))

    ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error)

    def progress_bar_life():
        cancelled = False
        while task:
            if task[0].isCancelled():
                cancelled = True
                break
            sleep(1)

        interrupt()

        if task:
            del task[0]

        ws.close()

        if cancelled:
            save_image_node.knob('backup_result').setEnabled(True)
            save_image_node.knob('comfyui_submit').setEnabled(True)
            nuke.comfyui_running = False
            return

        def post(n):
            try:
                post_submit(n)
            except:
                nuke.executeInMainThread(
                    nuke.message, args=(traceback.format_exc()))

        nuke.executeInMainThread(post, args=(save_image_node))

        save_image_node.knob('backup_result').setEnabled(True)
        save_image_node.knob('comfyui_submit').setEnabled(True)
        nuke.comfyui_running = False

    threading.Thread(target=ws.run_forever).start()
    threading.Thread(target=progress_bar_life).start()


def extract_data():
    this = nuke.thisNode()
    nodes = get_connected_comfyui_nodes(this, ignore_nodes=['SaveImage'])
    nodes.append((this, extract_node_data(this)))
    nuke.root().knob('proxy').setValue(False)

    comfyui_nodes = [n.name() for n, _ in nodes]
    data = {}
    input_node_changed = False

    for n, node_data in nodes:
        if not check_node(n):
            return {}, None

        class_type = node_data['class_type']

        if class_type == 'KSampler':
            if not n.knob('fixed_seed').value():
                random_value = random.randrange(1, 9999)
                n.knob('seed_').setValue(random_value)
                node_data['inputs']['seed'] = random_value

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

    current_state = {'connected_nodes': state.strip()}

    try:
        prev_state = jread(state_file)
    except:
        prev_state = {}

    load_image_data = {
        'inputs': {
            'directory': '',
            'image_load_cap': 0,
            'select_every_nth': 1,
            'skip_first_images': 0
        },
        'class_type': 'VHS_LoadImages'
    }

    input_dir = '{}/input'.format(get_comfyui_dir())

    if current_state.get('connected_nodes') == prev_state.get('connected_nodes'):
        dirname = prev_state.get('dirname', 'none')
        sequence_dir = os.path.join(input_dir, dirname)

        if os.path.isdir(sequence_dir):
            if os.listdir(sequence_dir):
                load_image_data['inputs']['directory'] = dirname
                return load_image_data, False, False

    dirname = '{}_{}'.format(get_project_name(), node.fullName())
    sequence_dir = os.path.join(input_dir, dirname)

    if os.path.isdir(sequence_dir):
        shutil.rmtree(sequence_dir)

    os.mkdir(sequence_dir)
    filename = '{}/{}_#####.png'.format(sequence_dir, dirname)

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
    write.knob('colorspace').setValue('sRGB')
    write.knob('raw').setValue(False)
    write.knob('file_type').setValue('png')
    write.knob('channels').setValue('rgba' if alpha else 'rgb')

    try:
        nuke.execute(write, node.firstFrame(), node.lastFrame())
    except:
        nuke.delete(invert)
        nuke.delete(write)
        return {}, None, True

    nuke.delete(invert)
    nuke.delete(write)

    current_state['dirname'] = dirname
    jwrite(state_file, current_state)

    load_image_data['inputs']['directory'] = dirname
    return load_image_data, True, False


def outside_read(save_image_node, reload=False):
    save_image_node.begin()
    inside_read = nuke.toNode('read')
    save_image_node.end()

    name = '{}Read'.format(save_image_node.name())
    outside_read = save_image_node.knob('outside_read').value()

    save_image_node.parent().begin()

    if not outside_read:
        nuke.delete(nuke.toNode(name))
        return

    read = nuke.toNode(name)
    if not read:
        read = nuke.createNode('Read', inpanel=False)

    read.setXYpos(save_image_node.xpos(), save_image_node.ypos() + 35)
    read.knob('tile_color').setValue(
        save_image_node.knob('tile_color').value())
    read.knob('on_error').setValue('black')

    read.setName(name)

    for knobname in ['file', 'first', 'last', 'origlast', 'origfirst', 'colorspace', 'raw']:
        read.knob(knobname).setValue(inside_read.knob(knobname).value())

    if reload:
        read.knob('reload').execute()

    save_image_node.parent().end()


def get_filename_prefix(save_image_node):
    filename_prefix = '{}_{}'.format(
        get_project_name(), save_image_node.fullName())
    return filename_prefix


def post_submit(save_image_node):
    prefix = get_filename_prefix(save_image_node)
    output_dir = '{}/output'.format(get_comfyui_dir())
    sequence_dir = '{}/{}'.format(output_dir, prefix)

    shutil.rmtree(sequence_dir, ignore_errors=True)
    os.mkdir(sequence_dir)

    frames = save_image_node.input(0).lastFrame()
    last_frame = 0

    for i in range(frames):
        frame = '00000{}'.format(i + 1)[-5:]
        src = '{}/{}_{}_.png'.format(output_dir, prefix, frame)
        dst = '{}/{}_{}_.png'.format(sequence_dir, prefix, frame)

        if os.path.isfile(src):
            shutil.move(src, dst)
            last_frame = i + 1

    # en el 'for' superior ya se copian las imagenes por rango de frames, pero a veces
    # cuando hay 1 imagen comfyui comienza del padding 2 y no coincide con los frames
    for f in os.listdir(output_dir):
        if os.path.isdir(os.path.join(output_dir, f)):
            continue

        if prefix + '_' in f:
            shutil.move(os.path.join(output_dir, f),
                        os.path.join(sequence_dir, f))

    filename = '{}/{}_#####_.png'.format(sequence_dir, prefix)

    save_image_node.begin()
    read = nuke.toNode('read')
    output_node = nuke.toNode('Output')
    save_image_node.end()

    output_node.setInput(0, read)
    read.knob('file').setValue(filename)
    read.knob('first').setValue(1)
    read.knob('last').setValue(last_frame)
    read.knob('origfirst').setValue(1)
    read.knob('origlast').setValue(last_frame)
    read.knob('reload').execute()

    outside_read(save_image_node, reload=True)
