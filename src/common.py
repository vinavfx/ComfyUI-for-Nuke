# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from datetime import datetime
import json
import hashlib
import bz2
import base64
from ..settings import *
from ..nuke_util.nuke_util import get_connected_nodes
import threading

image_inputs = []
mask_inputs = []
updated_inputs = False


def show_message(msg):
    if nuke.GUI:
        execute_in_main_thread(nuke.message, (msg, ))
    else:
        print(msg)


def execute_in_main_thread(func, args=(), kwargs=None):
    if kwargs is None:
        kwargs = {}

    if nuke.GUI and not threading.current_thread().name == 'MainThread':
        return nuke.executeInMainThread(func, args=args, kwargs=kwargs)

    return func(*args, **kwargs)


def update_images_and_mask_inputs(settings):
    global image_inputs, mask_inputs, updated_inputs

    if updated_inputs:
        return

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

    if len(image_inputs) > 50:
        updated_inputs = True


def jsondumps(data):
    json_bytes = json.dumps(data, separators=(',', ':')).encode('utf-8')
    compressed_bytes = bz2.compress(json_bytes, compresslevel=9)
    return base64.b85encode(compressed_bytes).decode('utf-8')


def jsonloads(data):
    try:
        compressed_bytes = base64.b85decode(data.encode('utf-8'))
        json_bytes = bz2.decompress(compressed_bytes)
        return json.loads(json_bytes.decode('utf-8'))
    except:
        return {}


def get_date_code():
    now = datetime.now()
    ms = str(int(now.microsecond / 1000)).zfill(3)
    return now.strftime("%Y%m%d%H%M%S") + ms


def get_name_code(name, length=15):
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    num = int(h, 16)
    code = str(num % (10**length)).zfill(length)
    return code


def override_settings(run_node, settings):
    override_node = None
    for n in get_connected_nodes(run_node, ignore_disabled=True,
                                 continue_at_up_level=True, active_switch=True):
        if n.knob('override_settings'):
            override_node = n
            break

    if override_node and override_node.knob('override_settings'):
        def override(key):
            knob = override_node.knob(key)
            if knob:
                settings[key.upper()] = override_node.knob(key).value()

        override('url')
        override('background_submit')
        override('collect_directory')
        override('use_exr_to_load_images')
        override('display_meta_in_read_node')


def get_settings(run_node=None):
    settings = {
        'URL': URL,
        'OUTPUT_DIRECTORY': OUTPUT_DIRECTORY,
        'INPUT_DIRECTORY': INPUT_DIRECTORY,
        'COLLECT_DIRECTORY': COLLECT_DIRECTORY,
        'UPDATE_MENU_AT_START': UPDATE_MENU_AT_START,
        'USE_EXR_TO_LOAD_IMAGES': USE_EXR_TO_LOAD_IMAGES,
        'DISPLAY_META_IN_READ_NODE': DISPLAY_META_IN_READ_NODE,
        'BACKGROUND_SUBMIT': False
    }

    override_settings(run_node, settings)
    return settings
