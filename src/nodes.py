# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import json
import os
import re
import shutil
import random
import traceback
from collections import Counter
import nuke  # type: ignore

from ..nuke_util.nuke_util import (
    get_connected_nodes,
    get_project_name,
    get_user_path,
)
from .common import (
    image_inputs,
    mask_inputs,
    get_name_code,
    show_message,
    jsondumps,
    jsonloads,
)

states = {}


def extract_data(run_node, settings, input_links=None):
    output_node = get_input(run_node, 0)

    if not output_node:
        message = "Run is not connected!"
        show_message(message)
        return {}, None, message

    output_node_data = get_node_data(output_node)
    if not output_node_data.get("output_node", False):
        message = "Connect only to output nodes like SaveImage or SaveEXR !"
        show_message(message)
        return {}, None, message

    nodes = get_connected_comfyui_nodes(run_node)
    nuke.root().knob("proxy").setValue(False)

    for node, _ in nodes:
        if not check_node(node, input_links):
            return {}, None, "Invalid node connection!"

    comfyui_nodes = [n.name() for n, _ in nodes]
    data = {}
    input_node_changed = False
    rendered_nodes = set()

    for n, node_data in nodes:
        if n.knob("randomize"):
            if n.knob("randomize").value():
                random_value = random.randrange(1, 9999)

                seed_knob = next(
                    (
                        n.knob(k)
                        for k in ("seed_", "noise_seed_", "value_")
                        if n.knob(k)
                    ),
                    None,
                )

                if seed_knob:
                    seed_knob.setValue(random_value)
                    node_data["inputs"][seed_knob.name()[:-1]] = random_value

        for key in image_inputs + mask_inputs:
            input_key = node_data["inputs"].get(key)
            if not input_key or type(input_key) is not list:
                continue

            input_fullname = "{}.{}".format(n.parent().fullName(), input_key[0])

            if not input_fullname.startswith("root."):
                input_fullname = "root." + input_fullname

            with nuke.Root():
                input_node = nuke.toNode(input_fullname) if input_key else None

            run_node.begin()

            if not input_node:
                continue

            linked_input = (input_links or {}).get(input_node.fullName())
            if linked_input is not None:
                node_data["inputs"][key] = list(linked_input)
                continue

            if is_switch_any(input_node):
                continue

            if is_null_input(input_node):
                continue

            if not input_node.name() in comfyui_nodes:
                (
                    load_image_data,
                    changed_node,
                    execution_canceled,
                ) = create_load_images_and_save(input_node, settings, rendered_nodes)

                if execution_canceled:
                    return {}, None, "Image rendering was canceled!"

                # nuke_attrs used in "copy_workflow"
                load_image_data["nuke_attrs"] = {
                    "xpos": input_node.xpos(),
                    "ypos": input_node.ypos(),
                    "tile_color": input_node["tile_color"].value(),
                }

                input_node_changed = True if changed_node else input_node_changed
                data[input_node.name()] = load_image_data

        # nuke_attrs used in "copy_workflow"
        node_data["nuke_attrs"] = {
            "xpos": n.xpos(),
            "ypos": n.ypos(),
            "tile_color": n["tile_color"].value(),
        }
        data[n.name()] = node_data

    return data, input_node_changed, ""


def state_node(node):
    connected_nodes = get_connected_nodes(node, continue_at_up_level=True)
    connected_nodes = [n for n in connected_nodes if not n.Class() == "Dot"]
    connected_nodes.append(node)
    state = ""

    ct = nuke.nodes.CurveTool(
        inputs=[node], operation="Avg Intensities", channels="rgba"
    )
    ct["ROI"].setValue([0, 0, node.width(), node.height()])
    nuke.execute(ct, node.firstFrame(), node.firstFrame())
    intensity_data = ct["intensitydata"]
    rgba = [
        round(intensity_data.value(index), 5)
        for index in range(intensity_data.arraySize())
    ]
    nuke.delete(ct)

    attrs = [
        rgba,
        len(connected_nodes),
        node.firstFrame(),
        node.lastFrame(),
        node.width(),
        node.height(),
        node.bbox().x(),
        node.bbox().y(),
        node.bbox().w(),
        node.bbox().h(),
    ]

    state += ",".join([str(i) for i in attrs])
    knobs_analyze = ["disable", "name"]

    for n in connected_nodes:
        knobs_state = ""

        for k in n.knobs().values():
            if not k.visible() or not k.enabled():
                continue

            if not k.name() in knobs_analyze:
                continue

            if k.hasExpression() or k.isAnimated():
                try:
                    value = k.valueAt(0)
                except Exception:
                    value = k.toScript()
            else:
                value = k.toScript()

            knobs_state += "{} ".format(value)

        state += knobs_state

    return state


def create_load_images_and_save(node, settings, rendered_nodes):
    state = state_node(node)

    current_state = {"connected_nodes": state.strip(), "state_id": 0}
    prev_state = states.get(node.fullName(), {})

    frame_range = [node.firstFrame(), node.lastFrame()]
    load_image_data = {
        "frame_range": frame_range,
        "inputs": {
            "filepath": "",
            "format": "exr",
            "tonemap": "sRGB",
        },
        "class_type": "ReadImage",
    }

    if (
        current_state.get("connected_nodes") == prev_state.get("connected_nodes")
        or node in rendered_nodes
    ):
        sequence_dir = prev_state.get("sequence_dir", "none")
        filepath = prev_state.get("filepath", "none")
        if (
            os.path.isdir(sequence_dir)
            and os.listdir(sequence_dir)
            and prev_state.get("format") == "exr"
        ):
            load_image_data["inputs"]["filepath"] = filepath
            load_image_data["inputs"]["id"] = prev_state.get("state_id", 0)
            return load_image_data, False, False

    dirname = get_name_code(
        "{}{}{}{}{}".format(
            os.path.basename(get_user_path()),
            get_project_name(),
            node.fullName(),
            frame_range[0],
            frame_range[1],
        )
    )

    sequence_dir = os.path.join(settings["INPUT_DIRECTORY"], dirname)
    filepath = sequence_dir

    if os.path.isdir(sequence_dir):
        shutil.rmtree(sequence_dir)

    os.makedirs(sequence_dir)
    filename = "{}/{}_#####.exr".format(sequence_dir, dirname)

    [n.setSelected(False) for n in nuke.selectedNodes()]

    crop = nuke.createNode("Crop", inpanel=False)
    crop.knob("box").setValue([0, 0, node.width(), node.height()])
    crop.setInput(0, node)
    crop.setXYpos(node.xpos(), node.ypos())

    clamp = nuke.createNode("Clamp", inpanel=False)
    clamp.setInput(0, crop)

    write = nuke.createNode("Write", inpanel=False)
    write.knob("hide_input").setValue(True)
    write.setName(node.name() + "_write")
    write.setXYpos(node.xpos(), node.ypos())
    write.setSelected(False)
    write.setInput(0, clamp)
    write.knob("file").setValue(filename)
    write.knob("file_type").setValue("exr")
    write.knob("raw").setValue(True)
    write.knob("channels").setValue("rgba")

    def clean():
        nuke.delete(write)
        nuke.delete(crop)
        nuke.delete(clamp)

    try:
        nuke.execute(write, node.firstFrame(), node.lastFrame())
    except Exception:
        clean()
        show_message(traceback.format_exc())
        return {}, False, True

    clean()

    state_id = random.randrange(1, 9999)
    current_state["sequence_dir"] = sequence_dir
    current_state["filepath"] = filepath
    current_state["format"] = "exr"
    current_state["state_id"] = state_id

    states[node.fullName()] = current_state
    rendered_nodes.add(node)

    load_image_data["inputs"]["filepath"] = filepath
    load_image_data["inputs"]["id"] = state_id

    return load_image_data, True, False


def get_connected_comfyui_nodes(root_node, visited=None, ignore_nodes=[]):
    if visited is None:
        visited = set()

    def is_disabled(n):
        disable_knob = n.knob("disable")
        if not disable_knob:
            return

        if disable_knob.value():
            return True

    sd_nodes = []

    for i in range(root_node.maxInputs()):
        inode = root_node.input(i)

        if not inode:
            continue

        if not i == 0 and is_disabled(root_node):
            continue

        if is_switch_any(root_node):
            if not root_node.knob("which").value() == i:
                continue

        if is_null_input(root_node) and not is_disabled(root_node):
            continue

        if inode in visited:
            continue

        node_data = extract_node_data(inode)
        if node_data:
            if node_data["class_type"] in ignore_nodes:
                continue

        visited.add(inode)

        if not is_disabled(inode) and node_data:
            sd_nodes.append((inode, node_data))

        sd_nodes.extend(get_connected_comfyui_nodes(inode, visited, ignore_nodes))

    return sd_nodes


def get_node_data(node):
    data_knob = node.knob("data")

    if not data_knob:
        return {}

    data = jsonloads(data_knob.value())
    if data:
        return data

    # Codigo para nodos viejos, borrar mas adelante!
    value = data_knob.value()
    if "class_type" not in value:
        return {}

    data = (
        value.split("#")[0]
        .replace("'", '"')
        .replace("True", "true")
        .replace("False", "false")
    )
    return json.loads(data)


def save_node_data(node, data):
    node.knob("data").setValue(jsondumps(data))


def extract_node_data(node):
    data = get_node_data(node)
    if not data:
        return {}

    inputs = {}
    knobs_input_names = data.get("knobs_input_names", {})

    for knob in node.knobs().values():
        if not knob.name()[-1:] == "_":
            continue

        if isinstance(knob, nuke.File_Knob):
            frame = int(nuke.frame())
            value = knob.evaluate(frame)
            padding = re.search(r"%0?(\d*)d", knob.value())
            if padding:
                width = int(padding[1] or 1)
                prefix, suffix = value.rsplit(padding[0] % frame, 1)
                value = prefix + "#" * width + suffix
        elif hasattr(knob, "valueAt"):
            value = (
                knob.valueAt(1)
                if knob.isAnimated() and not knob.hasExpression()
                else knob.value()
            )
        else:
            value = knob.value()

        if type(knob) is nuke.Enumeration_Knob:
            try:
                value = float(value)
            except Exception:
                pass

        elif type(knob) is nuke.Multiline_Eval_String_Knob:
            value = knob.toScript()

        if type(value) is float or type(value) is int:
            value = int(value) if int(value) == value else value

        name = knobs_input_names.get(knob.name(), knob.name()[:-1])
        inputs[name] = value

    for i in range(node.maxInputs()):
        inode = get_input(node, i)

        if not inode:
            continue

        ignore = data["inputs"][i].get("ignore", False)
        if ignore:
            continue

        input_name = data["inputs"][i]["name"]
        output_index = 0

        if not get_node_data(inode):
            if input_name in image_inputs:
                output_index = 0
            elif input_name in mask_inputs:
                output_index = 1
        else:
            output_index = get_output_index(node, data, i)
            if output_index == -2:
                continue

        if input_name in inputs:
            continue

        inputs[input_name] = [inode.name(), output_index]

    # TODO: Remove this temporary compatibility layer once embedded legacy
    # SaveImage and SaveEXR nodes are no longer used in existing projects.
    class_type = data["class_type"]
    if class_type in ("SaveImage", "SaveEXR", "SaveExr"):
        inputs = {
            key: inputs[key] for key in ("images", "filename_prefix") if key in inputs
        }
        inputs.update(
            format="exr",
            bit_depth="16bit",
            compression="Zip (16 scanlines)",
            color_space="linear",
        )
        class_type = "WriteImage"

    # Restore after:
    # return {"inputs": inputs, "class_type": data["class_type"]}
    # --------------------------------------------------------------------

    return {"inputs": inputs, "class_type": class_type}


def connection_types_match(input_class, output_class):
    input_types = {item.strip() for item in input_class.split(",")}
    output_types = {item.strip() for item in output_class.split(",")}
    return "*" in input_types or "*" in output_types or bool(input_types & output_types)


def get_output_index(node, node_data, input_index):
    inode_data = get_node_data(get_input(node, input_index))
    if not inode_data:
        return -2

    inode_outputs = inode_data["outputs"]
    allowed_outputs = node_data["inputs"][input_index]["outputs"]

    force_output = node_data["inputs"][input_index].get("force_output")
    if force_output is not None:
        return force_output

    for allowed_output in allowed_outputs:
        for i, o in enumerate(inode_outputs):
            if connection_types_match(allowed_output, o):
                return i

    return -1


def check_node(node, input_links=None):
    node_data = get_node_data(node)

    for i in range(node.maxInputs()):
        inode = get_input(node, i)

        index_data = node_data["inputs"][i]
        input_name = index_data["name"]
        optional_input = index_data.get("opt", False)

        if optional_input and not inode:
            continue

        if not inode:
            show_message(
                node.name() + ' : "{}" input disconnected !'.format(input_name)
            )
            return

        if input_links and inode.fullName() in input_links:
            if input_name not in image_inputs:
                show_message(
                    "Unified workflows only support image connections between gizmos."
                )
                return
            continue

        inode_data = get_node_data(inode)

        if not inode_data:
            if input_name in image_inputs + mask_inputs:
                pixel_aspect = inode.pixelAspect()
                if pixel_aspect != 1:
                    message = (
                        "Pixel aspect ratio {:g}:1 is not supported.\n"
                        "Only 1:1 is allowed. Inference stopped."
                    ).format(pixel_aspect)
                    show_message(message)
                    return

                if inode.bbox().w() < 10 or inode.bbox().h() < 10:
                    message = (
                        '{}: input "{}" not connected or bbox without '
                        "information in some frame !"
                    ).format(node.name(), input_name)
                    show_message(message)
                    return
                continue

            else:
                show_message(
                    '{}: "{}" does not support "{}" !'.format(
                        node.name(), input_name, inode.name()
                    )
                )
                return

        inode_outputs = inode_data["outputs"]
        input_data = node_data["inputs"][i]
        allowed_outputs = input_data["outputs"]

        if "*" not in allowed_outputs and "*" not in inode_outputs:
            if not any(
                connection_types_match(allowed_output, output)
                for allowed_output in allowed_outputs
                for output in inode_outputs
            ):
                show_message(
                    node.name()
                    + ' : "{}" connection not supported !'.format(input_name)
                )
                return

        if requires_force_output(inode_outputs, allowed_outputs[0]):
            if input_data.get("force_output") is None:
                if nuke.ask(
                    "{}:\nConnected to node with duplicate outputs, "
                    "Connect now?".format(node.name())
                ):
                    from .scripts.force_output_connection import force_output

                    force_output(node)
                return

    return True


def requires_force_output(outputs, input_class):
    contador = Counter(outputs)
    repeated = [item for item, count in contador.items() if count > 1]

    if "*" in {item.strip() for item in input_class.split(",")} and len(outputs) > 1:
        pass
    else:
        if not repeated:
            return False

        if "*" not in repeated:
            if not any(connection_types_match(input_class, item) for item in repeated):
                return False

    return True


def update_input_nodes(node):
    for n in nuke.allNodes():
        if n.Class() == "Input":
            nuke.delete(n)

    data = get_node_data(node)

    for idx, i in enumerate(data["inputs"]):
        inode = nuke.createNode("Input", inpanel=False)
        inode.setName(i["name"])

        if idx == 0:
            nuke.toNode("Output1").setInput(0, inode)


def is_switch_any(node):
    if not node.Class() == "Switch":
        return

    if not node.knob("switch_any"):
        return

    return True


def is_null_input(node):
    if not node.Class() == "Group":
        return

    if not node.knob("null_input"):
        return

    return True


def get_external_input(node, index, resolve_source=False):
    source = node.input(index)
    visited = set()
    while source is not None:
        name = source.fullName()
        if name in visited:
            raise ValueError("Circular gizmo dependency: {}".format(name))
        visited.add(name)
        disable = source.knob("disable")
        if disable is not None and disable.value():
            source = source.input(0)
        elif source.Class() == "Switch" and source.knob("switch_any") is None:
            source = source.input(int(source["which"].value()))
        else:
            source_knob = (
                source.knobs().get("comfyui_source") if resolve_source else None
            )
            linked = (
                source_knob.getLinkedKnob()
                if source_knob is not None and hasattr(source_knob, "getLinkedKnob")
                else None
            )
            if linked is not None and linked.name() == "comfyui_gizmo":
                source = linked.node()
                continue
            return source
    return None


def get_input(node, i, ignore_disabled=True):
    if not node:
        return

    inode = node.input(i)

    for _ in range(100):
        if not inode:
            return

        disable_knob = inode.knob("disable")
        disabled_node = False

        if disable_knob and ignore_disabled:
            disabled_node = inode.knob("disable").value()

        if inode.Class() == "Dot" or disabled_node or inode.knob("override_settings"):
            if inode.input(0):
                inode = inode.input(0)
                continue
            else:
                return

        if is_switch_any(inode):
            which = int(inode.knob("which").value())
            if inode.input(which):
                inode = inode.input(which)
                continue
            else:
                return

        if is_null_input(inode):
            return

        return inode
