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
from time import sleep, time
import websocket
import json
import threading
import copy

from ..nuke_util.nuke_util import set_tile_color, get_connected_nodes, get_user_path, get_project_name
from .common import get_comfyui_dir, update_images_and_mask_inputs, get_settings, show_message
from .connection import POST
from .queue_manager import resolve_submission_target, interrupt
from .nodes import extract_data
from .read_media import create_read, update_filename_prefix, exr_filepath_fixed, resolve_filename


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


def execute_in_main_thread(func, args=(), kwargs=None):
    if kwargs is None:
        kwargs = {}

    if nuke.GUI:
        return nuke.executeInMainThread(func, args=args, kwargs=kwargs)

    return func(*args, **kwargs)


def submit(run_node=None, success_callback=None, force_queue=None):
    def success_callback_wrapper(read, run_node):
        if not success_callback:
            return

        if success_callback.__code__.co_argcount >= 2:
            success_callback(read, run_node)
        else:
            success_callback(read)

    total_time = time()
    run_node = run_node or nuke.thisNode()
    settings = get_settings(run_node)

    if not resolve_submission_target(settings, force_queue):
        return

    update_images_and_mask_inputs(settings)

    if settings['COMFYUI_LOCAL'] and not get_comfyui_dir(settings):
        return

    exr_filepath_fixed(run_node)
    settings['project_name'] = nuke.root().name()

    data, input_node_changed = extract_data(run_node, settings)
    if not data:
        return

    global states
    if data == states.get(run_node.fullName(), {}) and not input_node_changed:
        settings['filename_prefix'] = update_filename_prefix(run_node, False)
        filename = resolve_filename(run_node, data, settings, True)
        read = create_read(run_node, data, settings, filename)

        success_callback_wrapper(read, run_node)
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

    task_status = {'title': 'Inferencing',
                   'progress': 0, 'message': 'Waiting in Queue ...'}
    task = [nuke.ProgressTask(task_status['title'])]
    task[0].setMessage(task_status['message'])

    execution_error = [False]

    def set_task_progress(progress, message = ''):
        if not nuke.GUI:
            print('{} : {}%'.format(message or task_status['message'], progress))

        if not task:
            return

        task[0].setProgress(progress)
        task_status['progress'] = progress

        if message:
            task[0].setMessage(message)
            task_status['message'] = message

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
            execute_in_main_thread(
                update_node, args=(node, data, run_node, settings))

        elif type_data == 'progress':
            progress = int(data['value'] * 100 / float(data['max'] or 0.01))
            set_task_progress(progress)

        elif type_data == 'executing':
            node = data.get('node')

            if task:
                if node:
                    set_task_progress(0, node)
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

            execute_in_main_thread(
                error_node_style, args=(data.get('node_id'), True, execution_message))
            execute_in_main_thread(show_message, args=(error))

    def on_error(ws, error):
        ws.close()
        if task:
            del task[0]

        if 'connected' in str(error):
            return

        execution_error[0] = True
        execute_in_main_thread(show_message, args=('error: ' + str(error)))

    def progress_task_loop():
        cancelled = False
        while task:
            if task[0].isCancelled():
                if nuke.executeInMainThreadWithResult(lambda: nuke.ask(
                        'Are you sure? This will stop the ComfyUI inference')):
                    cancelled = True
                    break
                elif task:
                    task[0] = nuke.ProgressTask(task_status['title'])
                    task[0].setProgress(task_status['progress'])
                    task[0].setMessage(task_status['message'])

            sleep(.1)

        interrupt(settings, client_id)

        if task:
            del task[0]

        ws.close()

        if cancelled:
            return

        filename = resolve_filename(run_node, data, settings)

        execute_in_main_thread(
            progress_finished, args=(run_node, filename))

    def progress_finished(n, filename):
        try:
            read = create_read(n, data, settings, filename)
            success_callback_wrapper(read, run_node)

            if not execution_error[0]:
                remove_all_error_style(run_node)
                states[run_node.fullName()] = state_data

        except:
            if not nuke.GUI:
                print(traceback.format_exc())

            execute_in_main_thread(
                show_message, args=(traceback.format_exc()))

    headers = ["{}: {}".format(k, v) for k, v in settings['HTTP_HEADER'].items()]
    ws = websocket.WebSocketApp(url, header=headers, on_message=on_message, on_error=on_error)

    task_loop = None
    if not settings['BACKGROUND_SUBMIT']:
        threading.Thread(target=ws.run_forever).start()
        task_loop = threading.Thread(target=progress_task_loop)
        task_loop.start()

    error = POST('prompt', body, settings)

    if settings['BACKGROUND_SUBMIT'] and not error:
        show_message('Workflow sent to the ComfyUI Queue\n{}/output/{}'.format(
            settings['COMFYUI_DIR'], os.path.dirname(settings['filename_prefix'] or '')))

    if error:
        execution_error[0] = True
        if task:
            del task[0]
        show_message(error)

    if not nuke.GUI:
        task_loop.join() if task_loop else None
        print('\nPrompt executed in {} seconds'.format(round(time() - total_time, 1)))
