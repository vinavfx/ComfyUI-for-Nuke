# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import textwrap
import sys
import nuke  # type: ignore
import uuid
import traceback
from time import sleep
import websocket
import json
import threading
import copy

from ..nuke_util.nuke_util import set_tile_color
from ..env import IP, PORT
from .common import get_comfyui_dir, update_images_and_mask_inputs
from .connection import POST, interrupt, check_connection
from .nodes import extract_data, get_connected_comfyui_nodes
from .read_media import create_read, update_filename_prefix, exr_filepath_fixed

client_id = str(uuid.uuid4())[:32].replace('-', '')
states = {}


def error_node_style(node_name, enable, message=''):
    node = nuke.toNode(node_name)
    if not node:
        return

    if enable:
        set_tile_color(node, [0, 1, 1])
        message = ' '.join(message.split()[:30])
        formatted_message = '\n'.join(textwrap.wrap(message, width=30))
        node.knob('label').setValue('ERROR:\n' + formatted_message)
    else:
        node['tile_color'].setValue(0)
        node.knob('label').setValue('')


def remove_all_error_style(root_node):
    for n, _ in get_connected_comfyui_nodes(root_node):
        label_knob = n.knob('label')
        if 'ERROR' in label_knob.value():
            error_node_style(n.fullName(), False)


def show_text_uptate(node_name, data, queue_prompt_node):
    output = data.get('output', {})
    texts = output.get('text', [])
    text = texts[0] if texts else ''

    queue_prompt_node.parent().begin()
    show_text_node = nuke.toNode(node_name)

    if not show_text_node:
        return

    if not text:
        return

    text = text.replace('\n', '')
    text = text.encode('utf-8') if sys.version_info[0] < 3 else text
    formatted_text = '\n'.join(textwrap.wrap(text, width=50))

    text_knob = show_text_node.knob('text')
    if text_knob:
        text_knob.setValue(text)

    output_text_node = nuke.toNode(node_name + 'Output')
    if not output_text_node:
        return

    label = '( [value {}.name] )\n{}\n\n'.format(node_name, formatted_text)
    output_text_node.knob('label').setValue(label)
    xpos = show_text_node.xpos() - output_text_node.screenWidth() - 50
    ypos = show_text_node.ypos() - (output_text_node.screenHeight() / 2) + (show_text_node.screenHeight() / 2)
    output_text_node.knob('label')
    output_text_node.setXYpos(xpos, ypos)


def comfyui_submit():
    if not check_connection():
        return

    update_images_and_mask_inputs()

    if nuke.comfyui_running:
        nuke.message('Inference in execution !')
        return

    nuke.comfyui_running = True

    comfyui_dir = get_comfyui_dir()
    if not comfyui_dir:
        nuke.comfyui_running = False
        return

    queue_prompt_node = nuke.thisNode()
    exr_filepath_fixed(queue_prompt_node)

    data, input_node_changed = extract_data()

    if not data:
        nuke.comfyui_running = False
        return

    global states
    if data == states.get(queue_prompt_node.fullName(), {}) and not input_node_changed:
        nuke.comfyui_running = False
        create_read(queue_prompt_node)
        return

    update_filename_prefix(queue_prompt_node)
    data, _ = extract_data()

    state_data = copy.deepcopy(data)
    queue_prompt_node.knob('comfyui_submit').setEnabled(False)

    body = {
        'client_id': client_id,
        'prompt': data,
        'extra_data': {}
    }

    url = "ws://{}:{}/ws?clientId={}".format(IP, PORT, client_id)
    task = [nuke.ProgressTask('ComfyUI Connection...')]

    execution_error = [False]

    def on_message(_, message):
        message = json.loads(message)

        data = message.get('data', None)
        type_data = message.get('type', None)

        if not data:
            return

        elif type_data == 'executed':
            node = data.get('node')
            nuke.executeInMainThread(show_text_uptate, args=(node, data, queue_prompt_node))

        elif type_data == 'progress':
            progress = int(data['value'] * 100 / data['max'])
            if task:
                task[0].setProgress(progress)

        elif type_data == 'executing':
            node = data.get('node')

            if task:
                if node:
                    task[0].setMessage('Inference: ' + node)
                else:
                    del task[0]

        elif type_data == 'execution_error':
            execution_message = data.get('exception_message')
            error = 'Error: {}\n\n'.format(data.get('node_type'))
            error += execution_message + '\n\n'

            for tb in data.get('traceback'):
                error += tb + '\n'

            execution_error[0] = True

            if task:
                del task[0]

            nuke.executeInMainThread(
                error_node_style, args=(data.get('node_id'), True, execution_message))
            nuke.executeInMainThread(nuke.message, args=(error))

    def on_error(ws, error):
        ws.close()
        if task:
            del task[0]

        if 'connected' in str(error):
            return

        execution_error[0] = True
        nuke.executeInMainThread(nuke.message, args=('error: ' + str(error)))

    def progress_task_loop():
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
            queue_prompt_node.knob('comfyui_submit').setEnabled(True)
            nuke.comfyui_running = False
            return

        nuke.executeInMainThread(progress_finished, args=(queue_prompt_node))
        queue_prompt_node.knob('comfyui_submit').setEnabled(True)
        nuke.comfyui_running = False

    def progress_finished(n):
        try:
            create_read(n)

            if not execution_error[0]:
                remove_all_error_style(queue_prompt_node)
                states[queue_prompt_node.fullName()] = state_data

        except:
            nuke.executeInMainThread(
                nuke.message, args=(traceback.format_exc()))

    ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error)

    threading.Thread(target=ws.run_forever).start()
    threading.Thread(target=progress_task_loop).start()

    error = POST('prompt', body)

    if error:
        execution_error[0] = True
        if task:
            del task[0]
        nuke.comfyui_running = False
        nuke.message(error)
        queue_prompt_node.knob('comfyui_submit').setEnabled(True)

