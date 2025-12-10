# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
import json
from datetime import datetime
import hashlib
from ..settings import *
from ..nuke_util.nuke_util import get_connected_nodes

if not getattr(nuke, 'comfyui_running', False):
    nuke.comfyui_running = False

image_inputs = ['image', 'frames', 'pixels', 'images', 'src_images']
mask_inputs = ['mask', 'attn_mask', 'mask_optional']
updated_inputs = False


def show_message(msg):
    if nuke.GUI:
        nuke.message(msg)
    else:
        print(msg)


def update_images_and_mask_inputs(settings):
    global image_inputs, mask_inputs, updated_inputs

    if updated_inputs:
        return

    updated_inputs = True

    from .connection import GET
    info = GET('object_info', settings)
    if not info:
        return

    for _, data in info.items():
        input_data = data['input']
        required = input_data.get('required', {})
        optional = input_data.get('optional', {})

        for name, value in list(required.items()) + list(optional.items()):
            class_type = value[0]

            if class_type in ['*', 'IMAGE']:
                if not name in image_inputs:
                    image_inputs.append(name)

            if class_type in ['*', 'MASK']:
                if not name in mask_inputs:
                    mask_inputs.append(name)


def get_date_code():
    now = datetime.now()
    ms = str(int(now.microsecond / 1000)).zfill(3)
    return now.strftime("%Y%m%d%H%M%S") + ms


def get_name_code(name, length=15):
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    num = int(h, 16)
    code = str(num % (10**length)).zfill(length)
    return code


def get_settings(run_node=None):
    settings = {
        'COMFYUI_DIR': COMFYUI_DIR,
        'URL': URL,
        'COMFYUI_LOCAL': COMFYUI_LOCAL,
        'OUTPUT_DIRECTORY': OUTPUT_DIRECTORY,
        'UPDATE_MENU_AT_START': UPDATE_MENU_AT_START,
        'USE_EXR_TO_LOAD_IMAGES': USE_EXR_TO_LOAD_IMAGES,
        'DISPLAY_META_IN_READ_NODE': DISPLAY_META_IN_READ_NODE,
        'TEMPORAL_DIR': TEMPORAL_DIR,
        'HTTP_HEADER': {},
        'BACKGROUND_SUBMIT': False
    }

    override_node = None
    for n in get_connected_nodes(run_node, ignore_disabled=True, continue_at_up_level=True):
        if n.knob('override_settings'):
            override_node = n
            break

    if override_node and override_node.knob('override_settings'):
        def override(key):
            knob = override_node.knob(key)
            if knob:
                settings[key.upper()] = override_node.knob(key).value()

        override('comfyui_dir')
        override('url')
        override('background_submit')
        override('output_directory')
        override('use_exr_to_load_images')
        override('display_meta_in_read_node')
        settings['COMFYUI_LOCAL'] = not override_node.knob(
            'remote_comfyui').value()

        headers_value = override_node.knob(
            'headers').value().replace("'", '"').strip()
        if headers_value:
            try:
                headers = json.loads(headers_value)
            except Exception as e:
                show_message("Error parsing headers: {}".format(e))
                headers = {}
            settings['HTTP_HEADER'] = headers

    return settings


def get_server_comfyui_dir(settings):
    from .connection import GET
    info = GET('system_stats', settings)
    if not info:
        return '.'

    main_py = info['system']['argv'][0]
    return os.path.dirname(main_py)


def get_comfyui_dir(settings):
    COMFYUI_DIR = settings['COMFYUI_DIR']

    if not settings['COMFYUI_LOCAL']:
        return ''

    if os.path.isdir(os.path.join(COMFYUI_DIR, 'comfy')):
        return COMFYUI_DIR

    show_message('Directory "{}" does not exist'.format(COMFYUI_DIR))
    return ''
