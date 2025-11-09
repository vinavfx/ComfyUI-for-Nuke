# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import textwrap
import sys
import nuke  # type: ignore
import os
import traceback
from time import sleep
import websocket
import json
import threading
import copy

from ..nuke_util.nuke_util import set_tile_color, get_connected_nodes, get_user_path, get_project_name
from .common import get_comfyui_dir, update_images_and_mask_inputs, get_settings
from .connection import POST
from .queue_manager import resolve_submission_target, interrupt
from .nodes import extract_data
from .read_media import create_read, update_filename_prefix, exr_filepath_fixed, download_filename


states = {}
prompt_counter = 0


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
    for n in get_connected_nodes(root_node):
        label_knob = n.knob('label')
        if 'ERROR' in label_knob.value():
            error_node_style(n.fullName(), False)


def update_node(node_name, data, run_node, settings):
    if 'ShowText' in node_name:
        show_text_uptate(node_name, data, run_node)

    elif 'PreviewImage' in node_name:
        preview_image_update(node_name, data, settings)


def show_text_uptate(node_name, data, run_node):
    output = data.get('output', {})
    texts = output.get('text', [])
    text = texts[0] if texts else ''

    run_node.parent().begin()
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
    ypos = show_text_node.ypos() - (output_text_node.screenHeight() / 2) + \
        (show_text_node.screenHeight() / 2)
    output_text_node.knob('label')
    output_text_node.setXYpos(xpos, ypos)


def preview_image_update(node_name, data, settings):
    output = data.get('output', {})
    images = output.get('images', [])

    if not images:
        return

    filename = images[0].get('filename')
    if not filename:
        return

    preview_node = nuke.toNode(node_name)
    if not preview_node:
        return

    preview_node.begin()

    filename = '{}/temp/{}'.format(settings['COMFYUI_DIR'], filename)
    read = nuke.toNode('read')

    if not read:
        read = nuke.createNode('Read', inpanel=False)
        read.setName('read')

    read.knob('file').setValue(filename)
    nuke.toNode('Output1').setInput(0, read)

    preview_node.knob('postage_stamp').setValue(True)
    preview_node.end()



def submit(run_node=None, success_callback=None):
    run_node = run_node or nuke.thisNode()
    settings = get_settings(run_node)

    if not resolve_submission_target(settings):
        return

    update_images_and_mask_inputs(settings)

    if settings['COMFYUI_LOCAL'] and not get_comfyui_dir(settings):
        return

    exr_filepath_fixed(run_node)

    data, input_node_changed = extract_data(run_node, settings)
    if not data:
        return

    global states
    if data == states.get(run_node.fullName(), {}) and not input_node_changed:
        downloaded_filename = download_filename(run_node, data, settings)
        read = create_read(run_node, data, settings, downloaded_filename)

        if success_callback:
            success_callback(read)
        return

    settings['filename_prefix'] = update_filename_prefix(run_node)

    data, _ = extract_data(run_node, settings)
    if not data:
        return

    state_data = copy.deepcopy(data)

    global prompt_counter; prompt_counter += 1
    client_id = '{}:{}:{}'.format(os.path.basename(
        get_user_path()), get_project_name(), prompt_counter).replace(' ', '-')

    body = {
        'client_id': client_id,
        'prompt': data,
        'extra_data': {}
    }

    url = "{}/ws?clientId={}".format(settings['URL'].replace('http', 'ws'), client_id)
    task = [nuke.ProgressTask('Inferencing')]
    task[0].setMessage('Waiting in Queue ...')

    execution_error = [False]

    def on_message(_, message):
        try:
            message = json.loads(message)
        except:
            return

        data = message.get('data', None)
        type_data = message.get('type', None)

        if not data:
            return

        elif type_data == 'executed':
            node = data.get('node')
            nuke.executeInMainThread(
                update_node, args=(node, data, run_node, settings))

        elif type_data == 'progress':
            progress = int(data['value'] * 100 / data['max'])
            if task:
                task[0].setProgress(progress)

        elif type_data == 'executing':
            node = data.get('node')

            if task:
                if node:
                    task[0].setMessage(node)
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
                if nuke.executeInMainThreadWithResult(lambda: nuke.ask(
                        'Are you sure? This will stop the ComfyUI inference')):
                    cancelled = True
                    break
                elif task:
                    task[0] = nuke.ProgressTask('Inferencing')

            sleep(.1)

        interrupt(settings, client_id)

        if task:
            del task[0]

        ws.close()

        if cancelled:
            return

        downloaded_filename = download_filename(run_node, data, settings)
        nuke.executeInMainThread(
            progress_finished, args=(run_node, downloaded_filename))

    def progress_finished(n, downloaded_filename):
        try:
            read = create_read(n, data, settings, downloaded_filename)

            if success_callback:
                success_callback(read)

            if not execution_error[0]:
                remove_all_error_style(run_node)
                states[run_node.fullName()] = state_data

        except:
            nuke.executeInMainThread(
                nuke.message, args=(traceback.format_exc()))

    headers = ["{}: {}".format(k, v) for k, v in settings['HTTP_HEADER'].items()]
    ws = websocket.WebSocketApp(url, header=headers, on_message=on_message, on_error=on_error)

    if not settings['BACKGROUND_SUBMIT']:
        threading.Thread(target=ws.run_forever).start()
        threading.Thread(target=progress_task_loop).start()

    error = POST('prompt', body, settings)

    if settings['BACKGROUND_SUBMIT'] and not error:
        nuke.message('Workflow sent to the ComfyUI Queue')

    if error:
        execution_error[0] = True
        if task:
            del task[0]
        nuke.message(error)
