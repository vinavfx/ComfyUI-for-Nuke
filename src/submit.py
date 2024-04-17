# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import uuid
import traceback
import copy

import os
import shutil
from time import sleep
import websocket
import json
import threading

from ..nuke_util.nuke_util import get_project_name
from ..python_util.util import jwrite, jread
from ..settings import IP, PORT
from .common import get_comfyui_dir, state_dir
from .connection import send_request, interrupt
from .nodes import extract_data

client_id = str(uuid.uuid4())[:32].replace('-', '')


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

    state_data = copy.deepcopy(data)

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

    progress(save_image_node, state_file, state_data)


def progress(save_image_node, state_file, state_data):
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
                jwrite(state_file, state_data)
            except:
                nuke.executeInMainThread(
                    nuke.message, args=(traceback.format_exc()))

        nuke.executeInMainThread(post, args=(save_image_node))

        save_image_node.knob('backup_result').setEnabled(True)
        save_image_node.knob('comfyui_submit').setEnabled(True)
        nuke.comfyui_running = False

    threading.Thread(target=ws.run_forever).start()
    threading.Thread(target=progress_bar_life).start()


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
    filename = filename.replace('\\', '/')

    save_image_node.begin()
    read = nuke.toNode('read')
    output_node = nuke.toNode('Output')
    save_image_node.end()

    ocio = nuke.Root().knob('colorManagement').value()

    output_node.setInput(0, read)
    read.knob('file').setValue(filename)
    read.knob('first').setValue(1)
    read.knob('last').setValue(last_frame)
    read.knob('origfirst').setValue(1)
    read.knob('origlast').setValue(last_frame)
    read.knob('colorspace').setValue('sRGB' if ocio == 'Nuke' else 'Output - sRGB')
    read.knob('reload').execute()

    outside_read(save_image_node, reload=True)
