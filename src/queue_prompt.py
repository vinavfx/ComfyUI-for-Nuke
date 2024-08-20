# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import uuid
import traceback
from time import sleep
import websocket
import json
import threading

from ..env import IP, PORT
from .common import get_comfyui_dir, update_images_and_mask_inputs
from .connection import POST, interrupt
from .nodes import extract_data
from .read_media import create_read, update_filename_prefix, exr_filepath_fixed

client_id = str(uuid.uuid4())[:32].replace('-', '')


def comfyui_submit():
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
    update_filename_prefix(queue_prompt_node)
    exr_filepath_fixed(queue_prompt_node)
    data = extract_data()

    if not data:
        nuke.comfyui_running = False
        return

    queue_prompt_node.knob('comfyui_submit').setEnabled(False)

    body = {
        'client_id': client_id,
        'prompt': data,
        'extra_data': {}
    }

    error = POST('prompt', body)
    if error:
        nuke.comfyui_running = False
        nuke.message(error)
        queue_prompt_node.knob('comfyui_submit').setEnabled(True)
        return

    progress(queue_prompt_node)

    # se repite ya que es necesario para que websocket retorne error !
    POST('prompt', body)


def progress(queue_prompt_node):
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
            queue_prompt_node.knob('comfyui_submit').setEnabled(True)
            nuke.comfyui_running = False
            return

        def post(n):
            try:
                create_read(n)
            except:
                nuke.executeInMainThread(
                    nuke.message, args=(traceback.format_exc()))

        nuke.executeInMainThread(post, args=(queue_prompt_node))

        queue_prompt_node.knob('comfyui_submit').setEnabled(True)
        nuke.comfyui_running = False

    threading.Thread(target=ws.run_forever).start()
    threading.Thread(target=progress_bar_life).start()
