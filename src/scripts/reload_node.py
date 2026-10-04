from html import escape

import nuke  # type: ignore
from ...nuke_util.nuke_util import (
    selected_node,
    get_output_nodes,
    get_input_nodes,
    transfer_knobs,
)
from ..update_menu import (
    comfyui_nodes,
    create_comfyui_node,
    get_autogrow_inputs,
    get_comfyui_node_color,
    get_ordered_inputs,
    normalize_nodename,
    update_menu,
)
from ..nodes import get_node_data, save_node_data
from .knob2input import convert_knobs, get_swapped_knobs


def has_node_updates(node, data, definition):
    ordered_inputs, _ = get_ordered_inputs(definition)
    expected_knobs = []
    expected_inputs = []
    swapped_knobs, _ = get_swapped_knobs(node)
    swapped_knobs = swapped_knobs or {}

    for key, input_value, is_optional, _ in ordered_inputs:
        input_class = input_value[0]
        info = input_value[1] if len(input_value) == 2 else {}
        if not isinstance(info, dict):
            continue

        is_knob = isinstance(input_class, list) or input_class in (
            "INT",
            "FLOAT",
            "STRING",
            "BOOLEAN",
            "COMBO",
        )
        if info.get("forceInput", False) or not is_knob:
            expected_inputs.extend(
                name
                for name, input_type, _, _ in get_autogrow_inputs(
                    key, input_class, info, is_optional
                )
                if input_type
            )
            continue

        expected_knobs.append(normalize_nodename(key.replace(".", "__")) + "_")
        if swapped_knobs.get(key, {}).get("swapped_knob", False):
            expected_inputs.append(key)

    actual_knobs = [
        name
        for name in data.get("knobs_order", [])
        if node.knob(name) is not None or node.knob(name[:-1] + "_hide") is not None
    ]
    actual_inputs = [value["name"] for value in data["inputs"]]
    return sorted(expected_knobs) != sorted(actual_knobs) or sorted(
        expected_inputs
    ) != sorted(actual_inputs)


def transfer_reload_knobs(source_node, new_node):
    choices = {
        knob.name(): knob.values()
        for knob in new_node.allKnobs()
        if isinstance(knob, nuke.Enumeration_Knob)
    }

    tile_color = new_node["tile_color"].value()
    transfer_knobs(source_node, new_node, transfer_all=True)
    new_node["tile_color"].setValue(tile_color)

    for knob_name, values in choices.items():
        knob = new_node.knob(knob_name)
        value = knob.value()
        knob.setValues(values)
        if value in values:
            knob.setValue(value)


def reload_node():
    nodes = selected_node(False)

    if not nodes:
        nuke.message("Select at least 1 ComfyUI node!")
        return

    with nodes[0].parent():
        update_menu(lambda: reload_node_action(nodes))


def reload_node_action(nodes):
    updated_nodes = []
    not_updated_nodes = []
    unchanged_nodes = 0

    for node in nodes:
        data = get_node_data(node)
        if not data:
            continue

        class_type = data["class_type"]
        definition = comfyui_nodes.get(class_type)
        if not definition:
            not_updated_nodes.append(class_type)
            continue
        if not has_node_updates(node, data, definition):
            color = get_comfyui_node_color(
                normalize_nodename(definition["name"]), definition["category"]
            )
            if node["tile_color"].value() != color:
                node["tile_color"].setValue(color)
                updated_nodes.append(node.name())
            else:
                unchanged_nodes += 1
            continue

        name = node.name()
        node.setName("_aux_")
        swapped_knobs, _ = get_swapped_knobs(node)
        force_outputs = {
            n["name"]: n["force_output"] for n in data["inputs"] if "force_output" in n
        }

        with node.parent():
            new_node = create_comfyui_node(class_type, False, connect_selected=False)

            if not new_node:
                not_updated_nodes.append(class_type)
                node.setName(name)
                continue

            convert_knobs(new_node, get_node_data(new_node), swapped_knobs)

            new_data = get_node_data(new_node)
            for n in new_data["inputs"]:
                if n["name"] in force_outputs:
                    n["force_output"] = force_outputs[n["name"]]
            save_node_data(new_node, new_data)

            transfer_reload_knobs(node, new_node)
            new_node.setName(name)
            new_node.setSelected(False)

            for i, onode in get_output_nodes(node):
                onode.setInput(i, new_node)

            for i, inode in get_input_nodes(node):
                new_node.setInput(i, inode)

            new_node.setXYpos(node.xpos(), node.ypos())
            nuke.delete(node)
            updated_nodes.append(name)

    messages = []
    if updated_nodes:
        names = "<br>".join(escape(name) for name in updated_nodes)
        messages.append(
            '<font color="#98C379">{} reloaded nodes:<br>{}</font>'.format(
                len(updated_nodes), names
            )
        )
    if unchanged_nodes:
        messages.append("{} nodes unchanged".format(unchanged_nodes))
    if not_updated_nodes:
        names = "<br>".join(escape(name) for name in not_updated_nodes)
        messages.append(
            "{} nodes not installed:<br>{}".format(len(not_updated_nodes), names)
        )
    nuke.message("<br><br>".join(messages) if messages else "Select a ComfyUI node!")
