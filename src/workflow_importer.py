# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import textwrap
import os
import nuke  # type: ignore
from ..nuke_util.nuke_util import set_hex_color
from ..nuke_util.python_util import jread
from .update_menu import create_comfyui_node, normalize_nodename, update_menu
from .run import error_node_style
from .nodes import get_node_data
from .connection import convert_to_utf8
from .common import show_message
from ..settings import COMFYUI2NUKE
from .scripts.knob2input import convert_knobs


def center_nodes(nodes):
    min_x = min(node["xpos"].value() for node in nodes)
    min_y = min(node["ypos"].value() for node in nodes)

    for node in nodes:
        new_x = node["xpos"].value() - min_x
        new_y = node["ypos"].value() - min_y
        node.setXYpos(int(new_x), int(new_y))


def import_workflow():
    workflow_path = nuke.getFilename("Workflow", "*.json")
    if not workflow_path:
        return

    if not os.path.isfile(workflow_path):
        show_message("Please select a JSON file, not a folder")
        return

    data = jread(workflow_path)
    [n.setSelected(False) for n in nuke.selectedNodes()]

    if "nodes" not in data:
        show_message("Incompatible workflow, perhaps exported from 'Export(API)'")
        return

    if not update_menu():
        return

    created_nodes = {}
    not_installed = []
    nodes = []
    ignore_nodes = []

    for attrs in data["nodes"]:
        if attrs["type"] in ignore_nodes:
            continue

        node = create_comfyui_node(attrs["type"], inpanel=False)

        swapped_knobs = {}
        knobs_to_inputs_names = []

        for input_item in attrs.get("inputs", []):
            if "widget" in input_item and "name" in input_item["widget"]:
                name = input_item["widget"]["name"]
                knobs_to_inputs_names.append(name)

                swapped_knobs[name] = {
                    "class": input_item["type"].lower(),
                    "swapped_knob": True,
                }

        if node and swapped_knobs:
            convert_knobs(node, get_node_data(node), swapped_knobs)

        if attrs["type"] in ["Note", "MarkdownNote"]:
            node = nuke.createNode("StickyNote", inpanel=False)
            text = str(convert_to_utf8(attrs["widgets_values"][0]))
            formatted_note = "\n".join(textwrap.wrap(text, width=40))
            node.knob("label").setValue(formatted_note + "\n\n")

        elif attrs["type"] == "Reroute":
            node = nuke.createNode("Dot", inpanel=False)

        elif attrs["type"] in ("easy getNode", "easy setNode"):
            node = nuke.createNode("Dot", inpanel=False)
            prefix = "Get" if attrs["type"] == "easy getNode" else "Set"
            name = prefix + normalize_nodename(attrs["title"])
            node.setName(name)
            node.knob("label").setValue(normalize_nodename(attrs["title"]))

        elif not node:
            node = nuke.createNode("NoOp", inpanel=False)
            node.setName(normalize_nodename(attrs["type"]))
            error_node_style(node.fullName(), True, "Node not installed !")
            not_installed.append(attrs["type"])

        if not node.knob("tile_color").value():
            set_hex_color(node, attrs.get("bgcolor"))

        created_nodes[attrs["id"]] = (node, attrs, knobs_to_inputs_names)
        nodes.append(node)
        node.setSelected(False)

        pos = attrs["pos"]

        if isinstance(pos, list):
            xpos, ypos = attrs["pos"]
        else:
            xpos = attrs["pos"]["0"]
            ypos = attrs["pos"]["1"]

        node.setXYpos(int(xpos / 2), int(ypos / 2))

    for attrs in data["groups"]:
        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd.setName("GROUP")
        text = convert_to_utf8(attrs["title"])
        bd.knob("label").setValue(attrs["title"])
        bd.knob("bdwidth").setValue(attrs["bounding"][2] / 2)
        bd.knob("bdheight").setValue(attrs["bounding"][3] / 2)
        bd.setXYpos(int(attrs["bounding"][0] / 2), int(attrs["bounding"][1] / 2))
        bd.knob("z_order").setValue(0)
        bd.knob("note_font_size").setValue(30)
        set_hex_color(bd, attrs.get("color"))

        nodes.append(bd)
        bd.setSelected(False)

    if not nodes:
        return

    center_nodes(nodes)

    def find_node_link(link):
        if not link:
            return

        for node, attrs, _ in created_nodes.values():
            for odata in attrs.get("outputs", {}):
                links = odata["links"]
                if not links:
                    continue

                if link in links:
                    return node

    for node, attrs, knobs_to_inputs_names in created_nodes.values():
        node_data = {}

        if attrs["type"] in ("Reroute", "easy setNode"):
            knobs_order = []

        elif attrs["type"] == "easy getNode":
            knobs_order = []
            node_name = node.name().replace("Get", "Set")
            node.setInput(0, nuke.toNode(node_name))
            node.knob("hide_input").setValue(True)

        else:
            node_data = get_node_data(node)
            if not node_data:
                continue

            knobs_order = node_data["knobs_order"]

        widgets_values = attrs.get("widgets_values")
        widgets_values_named = attrs.get("widgets_values_named")
        knobs_input_names = node_data.get("knobs_input_names", {})
        values = []

        if isinstance(widgets_values_named, dict) and widgets_values_named:
            for knob_name in knobs_order:
                input_name = knobs_input_names.get(knob_name, knob_name[:-1])
                values.append(widgets_values_named.get(input_name))
        elif isinstance(widgets_values, list):
            for value in widgets_values:
                if value in ["fixed", "increment", "decrement", "randomize"]:
                    if any("seed" in s for s in knobs_order):
                        randomize_knob = node.knob("randomize")
                        if randomize_knob:
                            randomize_knob.setValue(not value == "fixed")
                        continue
                values.append(value)
        else:
            for knob_name in knobs_order:
                input_name = knobs_input_names.get(knob_name, knob_name[:-1])
                values.append(widgets_values[input_name])

        for i, value in enumerate(values):
            if i >= len(knobs_order) or value is None:
                continue

            value = convert_to_utf8(value)
            knob = node.knob(knobs_order[i])
            if not knob:
                continue

            if type(value) is int:
                value = value if value < 1e9 else 1e9
                knob.setValue(int(value))
            else:
                try:
                    knob.setValue(value)
                except Exception:
                    show_message(
                        'Could not set the knob "{}" value for this node "{}" !'.format(
                            knob.name(), node.name()
                        )
                    )

        for i, idata in enumerate(attrs.get("inputs", {})):
            link = idata["link"]

            if (
                idata["name"] + "_" in knobs_order
                and not idata["name"] in knobs_to_inputs_names
            ):
                continue

            onode = find_node_link(link)
            node.setInput(i, onode)

        if "Save" in attrs["type"]:
            run_nk = os.path.join(COMFYUI2NUKE, "nodes/ComfyUI/Run.nk")
            run_node = nuke.nodePaste(run_nk)
            run_node.setInput(0, node)
            run_node.setSelected(False)
            run_node.setXYpos(node.xpos(), node.ypos() + 25)
            nodes.append(run_node)

    [n.setSelected(True) for n in nodes]

    if not_installed:
        nodes_list = "\n".join(not_installed)
        show_message("You need to install these nodes in ComfyUI:\n\n" + nodes_list)
