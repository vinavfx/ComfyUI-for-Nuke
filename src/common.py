# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
from datetime import datetime
import hashlib
from ..settings import *
from ..nuke_util.nuke_util import get_input

if not getattr(nuke, 'comfyui_running', False):
    nuke.comfyui_running = False

image_inputs = ['image', 'frames', 'pixels', 'images', 'src_images']
mask_inputs = ['mask', 'attn_mask', 'mask_optional']
updated_inputs = False


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


def get_output_node(run_node):
    from .nodes import get_input

    node = get_input(run_node, 0)
    if node and node.knob('override_settings'):
        node = get_input(node, 0)
    return node


def get_settings(run_node=None):
    settings = {
        'COMFYUI_DIR': COMFYUI_DIR,
        'IP': IP,
        'PORT': PORT,
        'COMFYUI_LOCAL': COMFYUI_LOCAL,
        'IMAGE_OUTPUT_WITHIN_PROJECT': IMAGE_OUTPUT_WITHIN_PROJECT,
        'UPDATE_MENU_AT_START': UPDATE_MENU_AT_START,
        'USE_EXR_TO_LOAD_IMAGES': USE_EXR_TO_LOAD_IMAGES,
        'DISPLAY_META_IN_READ_NODE': DISPLAY_META_IN_READ_NODE,
        'TEMPORAL_DIR': TEMPORAL_DIR
    }

    override_node = get_input(run_node, 0)
    if override_node and override_node.knob('override_settings'):
        settings['COMFYUI_DIR'] = override_node.knob('comfyui_dir').value()
        settings['IP'] = override_node.knob('ip').value()
        settings['PORT'] = int(override_node.knob('port').value())
        settings['COMFYUI_LOCAL'] = not override_node.knob(
            'remote_comfyui').value()
        settings['USE_EXR_TO_LOAD_IMAGES'] = override_node.knob(
            'use_exr_to_load_images').value()
        settings['DISPLAY_META_IN_READ_NODE'] = override_node.knob(
            'display_meta_in_read_node').value()

    return settings


def get_comfyui_dir(settings):
    COMFYUI_DIR = settings['COMFYUI_DIR']

    if not settings['COMFYUI_LOCAL']:
        return COMFYUI_DIR

    if os.path.isdir(os.path.join(COMFYUI_DIR, 'comfy')):
        return COMFYUI_DIR

    nuke.message('Directory "{}" does not exist'.format(COMFYUI_DIR))

    return ''
