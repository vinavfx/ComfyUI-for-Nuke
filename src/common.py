# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from datetime import datetime
import json
import os
import hashlib
import bz2
import base64
from ..settings import (
    COLLECT_DIRECTORY,
    DISPLAY_META_IN_READ_NODE,
    INPUT_DIRECTORY,
    OUTPUT_DIRECTORY,
    UPDATE_MENU_AT_START,
    URL,
    USE_EXR_TO_LOAD_IMAGES,
)
from ..nuke_util.nuke_util import get_connected_nodes
from ..nuke_util.python_util import jread, jwrite
import threading

image_inputs = []
mask_inputs = []
updated_inputs = False
object_info = None
scan_thread_state = threading.local()


def init_scan_thread(force_scan=False):
    scan_thread_state.gui = threading.current_thread().name == "MainThread"
    from .connection import GET
    from .queue_manager import resolve_submission_target

    global object_info
    cache_path = "/tmp/comfyui2nuke_object_info.json"

    settings = get_settings()
    settings = resolve_submission_target(settings, 10)
    if not settings:
        object_info = None
        print("Could not load ComfyUI object_info.")
        return

    if not force_scan and os.path.exists(cache_path):
        try:
            object_info = jread(cache_path)
            print("ComfyUI loaded successfully.")
            return
        except (OSError, TypeError, json.JSONDecodeError):
            pass

    object_info = GET("object_info", settings, timeout=120)

    if object_info:
        try:
            jwrite(cache_path, object_info)
        except OSError:
            pass
        print("ComfyUI loaded successfully.")
    else:
        print("Could not load ComfyUI object_info.")


def get_object_info():
    if object_info is None:
        show_message("ComfyUI has not loaded yet. Please try again in a few seconds.")
    return object_info


def show_message(msg):
    if nuke.GUI and getattr(scan_thread_state, "gui", True):
        execute_in_main_thread(nuke.message, (msg,))
    else:
        print(msg)


def execute_in_main_thread(func, args=(), kwargs=None):
    if kwargs is None:
        kwargs = {}

    if nuke.GUI and not threading.current_thread().name == "MainThread":
        return nuke.executeInMainThread(func, args=args, kwargs=kwargs)

    return func(*args, **kwargs)


def update_images_and_mask_inputs():
    global image_inputs, mask_inputs, updated_inputs

    if updated_inputs:
        return True

    info = get_object_info()
    if not info:
        return False

    for _, data in info.items():
        input_data = data["input"]
        required = input_data.get("required", {})
        optional = input_data.get("optional", {})

        for name, value in list(required.items()) + list(optional.items()):
            class_type = value[0]

            if class_type in ["*", "IMAGE"]:
                if name not in image_inputs:
                    image_inputs.append(name)

            if class_type in ["*", "MASK"]:
                if name not in mask_inputs:
                    mask_inputs.append(name)

            if class_type != "COMFY_AUTOGROW_V3":
                continue

            template = value[1].get("template", {})
            template_input = template.get("input", {})
            prefix = template.get("prefix", "")
            for group in ("required", "optional"):
                for template_value in template_input.get(group, {}).values():
                    template_class = template_value[0]
                    for index in range(3):
                        input_name = "{}.{}{}".format(name, prefix, index)
                        if template_class in ["*", "IMAGE"]:
                            if input_name not in image_inputs:
                                image_inputs.append(input_name)
                        if template_class in ["*", "MASK"]:
                            if input_name not in mask_inputs:
                                mask_inputs.append(input_name)

    if len(image_inputs) > 50:
        updated_inputs = True
        return True

    return False


def jsondumps(data):
    json_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
    compressed_bytes = bz2.compress(json_bytes, compresslevel=9)
    return base64.b85encode(compressed_bytes).decode("utf-8")


def jsonloads(data):
    try:
        compressed_bytes = base64.b85decode(data.encode("utf-8"))
        json_bytes = bz2.decompress(compressed_bytes)
        return json.loads(json_bytes.decode("utf-8"))
    except Exception:
        return {}


def get_date_code():
    now = datetime.now()
    ms = str(int(now.microsecond / 1000)).zfill(3)
    return now.strftime("%Y%m%d%H%M%S") + ms


def get_name_code(name, length=15):
    h = hashlib.md5(name.encode("utf-8")).hexdigest()
    num = int(h, 16)
    code = str(num % (10**length)).zfill(length)
    return code


def override_settings(run_node, settings):
    override_node = None
    for n in get_connected_nodes(
        run_node, ignore_disabled=True, continue_at_up_level=True, active_switch=True
    ):
        if n.knob("override_settings"):
            override_node = n
            break

    if override_node and override_node.knob("override_settings"):

        def override(key):
            knob = override_node.knob(key)
            if knob:
                settings[key.upper()] = override_node.knob(key).value()

        override("url")
        override("background_submit")
        override("collect_directory")
        override("use_exr_to_load_images")
        override("display_meta_in_read_node")


def get_settings(run_node=None):
    settings = {
        "URL": URL,
        "OUTPUT_DIRECTORY": OUTPUT_DIRECTORY,
        "INPUT_DIRECTORY": INPUT_DIRECTORY,
        "COLLECT_DIRECTORY": COLLECT_DIRECTORY,
        "UPDATE_MENU_AT_START": UPDATE_MENU_AT_START,
        "USE_EXR_TO_LOAD_IMAGES": USE_EXR_TO_LOAD_IMAGES,
        "DISPLAY_META_IN_READ_NODE": DISPLAY_META_IN_READ_NODE,
        "BACKGROUND_SUBMIT": False,
    }

    override_settings(run_node, settings)
    return settings
