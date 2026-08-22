# -*- coding: utf-8 -*-
# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
from functools import partial
import re
import json
import nuke  # type: ignore
import threading

from ..nuke_util.nuke_util import set_tile_color, get_output_nodes
from .connection import convert_to_utf8
from ..settings import COMFYUI2NUKE
from .common import (
    AUTOGROW_INPUT_COUNT,
    show_message,
    jsondumps,
    get_object_info,
)

comfyui_nodes = {}
menu_updated = False


def normalize_nodename(name):
    if not name.strip():
        return "unnamed"

    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    if name and name[0].isdigit():
        name = "_" + name

    return name


def get_autogrow_inputs(key, input_class, info, is_optional):
    if input_class != "COMFY_AUTOGROW_V3":
        return [[key, input_class, is_optional, key]]

    template = info.get("template", {})
    template_input = template.get("input", {})
    prefix = template.get("prefix", "")
    inputs = []

    for group in ("required", "optional"):
        for template_value in template_input.get(group, {}).values():
            template_class = template_value[0]
            for index in range(AUTOGROW_INPUT_COUNT):
                display_name = "{}{}".format(prefix, index)
                input_name = "{}.{}".format(key, display_name)
                inputs.append([input_name, template_class, is_optional, display_name])

    return inputs


def get_nodes():
    if not comfyui_nodes:
        update()

    return comfyui_nodes


def create_comfyui_node(node_type, inpanel=True):
    node_data = comfyui_nodes.get(node_type)
    if not node_data:
        return

    return create_node(node_data, inpanel)


def refresh_models(node, knob_name, class_type):
    object_info = get_object_info()
    if not object_info:
        return

    knob = node.knob(knob_name)
    input_info = object_info[class_type]["input"]["required"][knob_name[:-1]]
    models = input_info[0]

    if models == "COMBO":
        models = input_info[1].get("options", [])

    value = knob.value()
    knob.setValues(models)
    knob.setValue(value)


def create_node(data, inpanel=True):
    try:
        selected_node = nuke.selectedNode()
    except Exception:
        selected_node = None

    n = nuke.createNode("Group", inpanel=inpanel)

    name = normalize_nodename(data["name"])
    display_name = normalize_nodename(data["display_name"])
    if display_name[0].isdigit():
        display_name = "_" + display_name

    n.setName(display_name)

    category = data["category"].split("/")[-1]

    if category == "loaders":
        set_tile_color(n, [0.57, 0.58, 0.48])
    elif category == "mask":
        set_tile_color(n, [0.33, 0.42, 0.77])
    elif "VAE" in name:
        set_tile_color(n, [0.08, 0.8, 0.97])
    elif "Save" in name:
        set_tile_color(n, [0.16, 1, 0.74])
    elif "Merge" in name or "Combine" in name:
        set_tile_color(n, [0.64, 0.62, 0.77])

    inputs = []

    input_data = data["input"]
    required = input_data.get("required", {})
    optional = input_data.get("optional", {})

    input_order = data.get("input_order", {})
    required_order = input_order.get("required", [])
    optional_order = input_order.get("optional", [])

    knobs_order = []
    knobs_class = {}

    for key in required_order + optional_order:
        input_value = required.get(key, [])
        is_optional = not input_value

        if is_optional:
            input_value = optional.get(key)

        input_class = input_value[0]
        info = input_value[1] if len(input_value) == 2 else {}

        if not type(info) == dict:
            continue

        if input_class == "COMFY_AUTOGROW_V3":
            inputs.extend(get_autogrow_inputs(key, input_class, info, is_optional))
            continue

        force_input = info.get("forceInput", False)
        default_value = info.get("default", 0)

        knob_name = key + "_"

        if force_input:
            inputs.extend(get_autogrow_inputs(key, input_class, info, is_optional))
            continue

        elif input_class == "INT":
            knob = nuke.Int_Knob(knob_name, key)
            default_value = default_value if default_value < 1e9 else 1e9
            knob.setValue(int(default_value))

        elif input_class == "FLOAT":
            min_value = info.get("min", 0)
            max_value = info.get("max", 1)

            knob = nuke.Double_Knob(knob_name, key)
            knob.setRange(min_value, max_value)
            knob.setValue(default_value)

        elif input_class == "STRING" and key in ["filepath", "file", "directory"]:
            knob = nuke.File_Knob(knob_name, key)

        elif input_class == "STRING":
            multiline = info.get("multiline", False)

            if multiline:
                knob = nuke.Multiline_Eval_String_Knob(knob_name, key)
            else:
                knob = nuke.String_Knob(knob_name, key)

            default_string = info.get("default", "")
            knob.setText(str(default_string))

        elif input_class in ["BOOLEAN", [True, False], [[True, False]]]:
            knob = nuke.Boolean_Knob(knob_name, key)
            knob.setFlag(nuke.STARTLINE)
            knob.setValue(default_value)

        elif type(input_class) == list or input_class == "COMBO":
            if input_class == "COMBO":
                options = info.get("options", [])
            else:
                options = input_class

            knob = nuke.Enumeration_Knob(knob_name, key, [str(i) for i in options])

            default_item = str(info.get("default", None))

            if not default_item == "None":
                knob.setValue(default_item)

        else:
            inputs.extend(get_autogrow_inputs(key, input_class, info, is_optional))
            continue

        n.addKnob(knob)
        knobs_order.append(knob.name())

        if input_class in ["INT", "STRING", "BOOLEAN", "FLOAT"]:
            knobs_class[knob.name()] = str(input_class).lower()

        if name in ["LoadAudio", "LoadImage"]:
            upload_knob = nuke.PyScript_Knob("upload", "+")
            upload_knob.setValue("comfyui.upload_and_download.upload_media()")
            n.addKnob(upload_knob)

        if category == "loaders" and "name" in knob_name:
            refresh_models_label = "Refresh Models"
            refresh_models_knob = nuke.PyScript_Knob(
                "refresh_models", refresh_models_label
            )
            refresh_models_command = (
                "comfyui.update_menu.refresh_models(nuke.thisNode(), "
            )
            refresh_models_command += '"{}", "{}")'.format(knob_name, data["name"])
            refresh_models_knob.setValue(refresh_models_command)
            n.addKnob(refresh_models_knob)

        is_primitive_value = data["name"] == "PrimitiveInt" and key == "value"
        if "seed" in key or is_primitive_value:
            randomize_knob = nuke.Boolean_Knob("randomize")
            randomize_knob.setValue(False)
            n.addKnob(randomize_knob)

    node_inputs = []

    n.begin()
    for key, input_class, is_optional, display_name in inputs:
        if not input_class:
            continue

        inode = nuke.createNode("Input", inpanel=False)
        inode.setName(normalize_nodename(display_name))

        node_inputs.append(
            {"name": key, "outputs": [input_class.lower()], "opt": is_optional}
        )

    nuke.createNode("Output", inpanel=False)
    n.end()

    data_knob = nuke.PyScript_Knob("data")
    data_knob.setVisible(False)

    outputs = []
    for output, output_name in zip(data["output"], data["output_name"]):
        if type(output) == list:
            outputs.append(output_name)
        else:
            outputs.append(output.lower())

    data_knob.setValue(
        jsondumps(
            {
                "knobs_order": knobs_order,
                "knobs_class": knobs_class,
                "class_type": data["name"],
                "output_name": data.get("output_name", False),
                "output_node": data.get("output_node", False),
                "inputs": node_inputs,
                "outputs": outputs,
            }
        )
    )

    n.addKnob(data_knob)

    if n.knob("User"):
        n.knob("User").setName("Controls")

    if selected_node:
        n.setXYpos(selected_node.xpos(), selected_node.ypos() + 24)
        n.setInput(0, selected_node)
        for i, onode in get_output_nodes(selected_node):
            onode.setInput(i, n)

    if "ShowText" in name:
        show_knob = nuke.Multiline_Eval_String_Knob("text", "")
        n.addKnob(show_knob)
        n.knob("text").setFlag(nuke.READ_ONLY)
        n.knob("onCreate").setValue(
            'nuke.thisNode().knob("text").setFlag(nuke.READ_ONLY)'
        )
        output_text_node = nuke.createNode("StickyNote", inpanel=False)
        output_text_node.setName(display_name + "Output")
        output_text_node.setXYpos(n.xpos() - 100, n.ypos())
        output_text_node.knob("label").setText("[value {}.name]".format(n.name()))
        n.setSelected(True)

    return n


def update_menu(callback=None):
    if menu_updated:
        return

    return update(callback)


def build_menu(info, progress, callback=None):
    global menu_updated
    menu_updated = True

    progress.setMessage("Refreshing menu items...")
    comfyui_menu = nuke.menu("Nodes").addMenu("ComfyUI")

    for item in comfyui_menu.items():
        if item.name() in ["Update all ComfyUI", "Basic Nodes", "Gizmos", "Scripts"]:
            continue

        if not hasattr(item, "clearMenu"):
            continue
        item.clearMenu()

    load_exr_exist = False
    nodes = {}

    def normalize_string(string):
        if not string:
            return ""

        string = "".join(char if ord(char) < 128 else "" for char in string)
        return string.replace(" /", "/").replace("/ ", "/").strip()

    for _, value in info.items():
        name = value["name"].replace("+", "")

        if name == "LoadEXR":
            load_exr_exist = True

        value["display_name"] = value.get("display_name") or value.get("name")
        display_name = normalize_string(value["display_name"])
        category = normalize_string(value["category"])

        if not category:
            category = "Uncategorized"

        value["category"] = category

        item_name = "{}/{}".format(category, display_name)
        nodes[item_name] = value

    if not load_exr_exist:
        show_message("ComfyUI-HQ-Image-Save module is required !")

    icon_gray = "{}/icons/comfyui_icon_gray.png".format(COMFYUI2NUKE)

    for i, (fullname, value) in enumerate(sorted(nodes.items())):
        progress.setProgress(int(i * 100 / len(nodes)))

        input_data = value.get("input", {})
        input_order = value.get("input_order", {})

        if not input_order:
            value["input_order"] = {
                "required": list(input_data.get("required", {})),
                "optional": list(input_data.get("optional", {})),
            }

        value = json.loads(json.dumps(value))
        value_utf8 = convert_to_utf8(value)

        comfyui_nodes[value["name"]] = value_utf8
        comfyui_menu.addCommand(
            fullname, partial(create_node, value_utf8), "", icon_gray
        )

    del progress

    if callback:
        callback()


def update(callback=None):
    def fetch_in_background():
        info = get_object_info()

        if info:
            progress = nuke.ProgressTask("Updating ComfyUI")
            progress.setMessage("Loading data from server...")
            progress.setProgress(0)
            nuke.executeInMainThread(partial(build_menu, info, progress, callback))

    thread = threading.Thread(target=fetch_in_background)
    thread.daemon = True
    thread.start()

    return True
