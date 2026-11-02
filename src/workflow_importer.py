# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import re
from contextvars import ContextVar

import nuke  # type: ignore

from ..nuke_util.arrange_nodes import arrange_candidates
from ..nuke_util.colors import set_tile_color_hex
from ..nuke_util.python_util import read_json_file
from ..settings import COMFYUI2NUKE
from .common import show_message, wait_for_comfyui
from .connection import convert_to_utf8
from .nodes import get_node_data, save_node_data
from .workflow_submission import error_node_style
from .scripts.knob2input import convert_knobs
from .update_menu import create_comfyui_node, normalize_nodename, update_menu
from .workflow_connections import read_metadata, write_metadata
from .workflow_flatten import (
    flatten_workflow,
    image_source,
    main_output_id,
    node_parents,
    replaced_ids,
    workflow_links,
)
from .workflow_templates import select_template

import_warnings = ContextVar("import_warnings")


def move_nodes_to_origin(nodes):
    if not nodes:
        return
    min_x = min(node.xpos() for node in nodes)
    min_y = min(node.ypos() for node in nodes)
    for node in nodes:
        node.setXYpos(node.xpos() - min_x, node.ypos() - min_y)


def import_workflow():
    panel = nuke.Panel("Import Workflow")
    panel.addEnumerationPulldown("Source", "ComfyUI\\ templates JSON\\ file")
    if not panel.show():
        return
    name = None
    if panel.value("Source") == "ComfyUI templates":
        data = select_template()
    else:
        workflow_path = nuke.getFilename("Workflow", "*.json")
        if not workflow_path:
            return
        if not os.path.isfile(workflow_path):
            show_message("Please select a JSON file, not a folder.")
            return
        try:
            data = read_json_file(workflow_path)
        except (OSError, ValueError) as error:
            show_message("Could not read the workflow: {}".format(error))
            return
        name = os.path.splitext(os.path.basename(workflow_path))[0]
    if data is not None:
        import_workflow_data(data, name)


def camel_case(name):
    parts = re.findall(r"[A-Za-z0-9]+", name)
    return normalize_nodename("".join(part[0].upper() + part[1:] for part in parts))


def import_workflow_data(data, name=None):
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        show_message("Incompatible workflow, perhaps exported from 'Export(API)'.")
        return
    if wait_for_comfyui(lambda: import_workflow_data(data, name)):
        return
    update_menu()
    definitions = {
        definition["id"]: definition
        for definition in data.get("definitions", {}).get("subgraphs", [])
    }
    not_installed = set()
    for node in nuke.selectedNodes():
        node.setSelected(False)
    undo = nuke.Undo()
    undo.begin("Import ComfyUI Workflow")
    warnings = []
    token = import_warnings.set(warnings)
    try:
        gizmo = create_workflow_gizmo(data, definitions, not_installed)
        if name:
            gizmo.setName(camel_case(name))
        gizmo.setSelected(True)
    except (KeyError, IndexError, ValueError, TypeError, RuntimeError) as error:
        show_message(
            "Could not import the workflow: {}. Use Undo to remove it.".format(error)
        )
    finally:
        import_warnings.reset(token)
        undo.end()
    if warnings:
        show_message("\n\n".join(dict.fromkeys(warnings)))
    if not_installed:
        show_message(
            "You need to install these nodes in ComfyUI:\n\n"
            + "\n".join(sorted(not_installed))
        )


def knob_for_input(node, name):
    data = get_node_data(node)
    names = data.get("knobs_input_names", {})
    knob_name = next((key for key, value in names.items() if value == name), name + "_")
    return node.knob(knob_name)


def widget_knob(node, name):
    if node is None:
        return None
    if name == "control_after_generate":
        return node.knob("randomize")
    return knob_for_input(node, name)


def set_widget_value(node, knob, value):
    if knob is None or value is None:
        return
    try:
        if knob.name() == "randomize":
            value = value != "fixed"
        if type(value) is int:
            value = min(value, 999999999)
        value = convert_to_utf8(value)
        if isinstance(knob, nuke.Enumeration_Knob) and isinstance(value, str):
            options = knob.values()
            if value not in options:
                knob.setValues(options + [value])
                message = (
                    'Preserved unavailable option "{}" for "{}.{}". '
                    "Make it available in ComfyUI before running.".format(
                        value, node.name(), knob.name()
                    )
                )
                warnings = import_warnings.get(None)
                if warnings is None:
                    show_message(message)
                else:
                    warnings.append(message)
        knob.setValue(value)
    except (TypeError, ValueError, RuntimeError):
        show_message('Could not set "{}.{}".'.format(node.name(), knob.name()))


def active_widget_names(data, values):
    order = data.get("knobs_order", [])
    names = data.get("knobs_input_names", {})
    dynamic_combos = data.get("dynamic_combos", {})
    input_names = [names.get(name, name[:-1]) for name in order]
    child_names = {
        child
        for options in dynamic_combos.values()
        for children in options.values()
        for child in children
    }
    active = []

    def add_input(name):
        if len(active) >= len(values):
            return
        value = values[len(active)]
        active.append(name)
        for child in dynamic_combos.get(name, {}).get(str(value), []):
            add_input(child)

    for name in input_names:
        if name not in child_names:
            add_input(name)
    return active


def set_widgets(node, attrs):
    data = get_node_data(node)
    order = data.get("knobs_order", [])
    names = data.get("knobs_input_names", {})
    values = attrs.get("widgets_values") or []
    named = attrs.get("widgets_values_named")
    if isinstance(named, dict) and named:
        values = named
    if isinstance(values, dict):
        values = [values.get(names.get(name, name[:-1])) for name in order]
    else:
        filtered = []
        for value in values:
            if value in ("fixed", "increment", "decrement", "randomize"):
                if any("seed" in name for name in order):
                    set_widget_value(node, node.knob("randomize"), value)
                    continue
            filtered.append(value)
        values = filtered
        if data.get("dynamic_combos"):
            knob_names = {names.get(name, name[:-1]): name for name in order}
            order = [
                knob_names[name]
                for name in active_widget_names(data, values)
                if name in knob_names
            ]
    for name, value in zip(order, values):
        set_widget_value(node, node.knob(name), value)


def create_workflow_node(attrs, not_installed):
    node_type = attrs["type"]
    node = create_comfyui_node(node_type, inpanel=False)
    if node_type in ("Reroute", "easy getNode", "easy setNode"):
        node = nuke.createNode("Dot", inpanel=False)
        if node_type != "Reroute":
            title = attrs.get("title", node_type)
            prefix = "Get" if node_type == "easy getNode" else "Set"
            node.setName(prefix + normalize_nodename(title))
            node["label"].setValue(title)
    elif not node:
        node = nuke.createNode("NoOp", inpanel=False)
        node.setName(normalize_nodename(node_type))
        error_node_style(node.fullName(), True, "Node not installed!")
        not_installed.add(node_type)
    set_widgets(node, attrs)
    swapped = {
        item["widget"]["name"]: {
            "class": str(item["type"]).lower(),
            "swapped_knob": True,
        }
        for item in attrs.get("inputs", [])
        if item.get("widget") and item.get("link") is not None
    }
    if swapped and get_node_data(node):
        convert_knobs(node, get_node_data(node), swapped)
    return node


def input_index(node, item, fallback):
    data = get_node_data(node)
    if data:
        return next(
            (
                index
                for index, value in enumerate(data["inputs"])
                if value["name"] == item["name"]
            ),
            None,
        )
    return fallback


def connect_link(node, index, source, slot):
    node.setInput(index, source)
    metadata = read_metadata(node, "comfyui_import_links")
    metadata[str(index)] = slot
    write_metadata(node, "comfyui_import_links", metadata)
    node_data = get_node_data(node)
    if node_data and get_node_data(source) and slot is not None:
        node_data["inputs"][index]["force_output"] = slot
        save_node_data(node, node_data)


def place_node(node, attrs):
    node.setSelected(False)
    if not node["tile_color"].value():
        set_tile_color_hex(node, attrs.get("bgcolor"))
    pos = attrs.get("pos", [0, 0])
    x, y = (pos["0"], pos["1"]) if isinstance(pos, dict) else pos
    node.setXYpos(int(x / 2), int(y / 2))


def connect_inputs(node, attrs, links, created):
    for fallback, item in enumerate(attrs.get("inputs", [])):
        index = input_index(node, item, fallback)
        if index is None:
            continue
        link = links.get(str(item.get("link")))
        source = created.get(str(link["origin_id"])) if link else None
        if source is None:
            node.setInput(index, None)
        else:
            connect_link(node, index, source, link["origin_slot"])


def connect_get_node(node, attrs, nodes, created):
    title = attrs.get("title", attrs["type"])
    source = next(
        (
            created[str(other["id"])]
            for other in nodes
            if other["type"] == "easy setNode" and other.get("title") == title
        ),
        None,
    )
    node.setInput(0, source)
    node["hide_input"].setValue(True)


def create_backdrop(attrs):
    backdrop = nuke.createNode("BackdropNode", inpanel=False)
    backdrop.setName("GROUP")
    backdrop["label"].setValue(convert_to_utf8(attrs.get("title", "")))
    x, y, width, height = attrs["bounding"]
    backdrop["bdwidth"].setValue(width / 2)
    backdrop["bdheight"].setValue(height / 2)
    backdrop.setXYpos(int(x / 2), int(y / 2))
    backdrop["z_order"].setValue(0)
    backdrop["note_font_size"].setValue(30)
    set_tile_color_hex(backdrop, attrs.get("color"))
    backdrop.setSelected(False)
    return backdrop


def build_flat_graph(flat, not_installed):
    created = {}
    links = workflow_links(flat)
    for attrs in flat["nodes"]:
        node = create_workflow_node(attrs, not_installed)
        place_node(node, attrs)
        created[str(attrs["id"])] = node
    for attrs in flat["nodes"]:
        node = created[str(attrs["id"])]
        connect_inputs(node, attrs, links, created)
        if attrs["type"] == "easy getNode":
            connect_get_node(node, attrs, flat["nodes"], created)
    for target, widget, value in flat["values"]:
        node = created.get(target)
        set_widget_value(node, widget_knob(node, widget), value)
    nodes = list(created.values())
    nodes.extend(create_backdrop(attrs) for attrs in flat["groups"])
    move_nodes_to_origin(nodes)
    return created, nodes


def build_graph(data, definitions, not_installed):
    return build_flat_graph(flatten_workflow(data, definitions), not_installed)


def connect_main_output(flat, created, write, run):
    parents = node_parents(flat)
    main = main_output_id(
        flat, parents, lambda key: get_node_data(created[key]).get("output_node")
    )
    if main is None:
        return None
    link = image_source(parents, main)
    if link is None:
        run.setInput(0, created[main])
        nuke.delete(write)
        return main
    origin = link["origin_id"]
    connect_link(write, 0, created[origin], link["origin_slot"])
    for key in replaced_ids(parents, main, origin):
        nuke.delete(created.pop(key))
    return origin


def enable_widget_sync(group):
    callback = (
        "import json\n"
        "node = nuke.thisNode()\n"
        "knob = nuke.thisKnob()\n"
        "metadata = json.loads(node['comfyui_widget_targets'].value())\n"
        "for target_path, target_name in metadata.get(knob.name(), []):\n"
        "    target = nuke.toNode(node.fullName() + '.' + target_path)\n"
        "    target_knob = target.knob(target_name) if target else None\n"
        "    if target_knob:\n"
        "        target_knob.setValue(node[knob.name()].value())"
    )
    existing = group["knobChanged"].value().rstrip()
    group["knobChanged"].setValue(existing + ("\n" if existing else "") + callback)


def expose_knob(group, knob, label, widgets):
    base_label = label
    suffix = 1
    while label in widgets:
        label = "{}_{}".format(base_label, suffix)
        suffix += 1
    name = normalize_nodename(label) or "control"
    if name[0].isdigit() or name.startswith("_"):
        name = "control" + name
    base = name
    suffix = 1
    while group.knob(name):
        name = "{}{}".format(base, suffix)
        suffix += 1
    link = nuke.Link_Knob(name, label)
    link.makeLink(relative_path(group, knob.node()), knob.name())
    group.addKnob(link)
    widgets[label] = name
    return name


def relative_path(group, node):
    prefix_length = len(group.fullName()) + 1
    return node.fullName()[prefix_length:]


def move_run_controls_to_end(group):
    knobs = [group.knob(name) for name in ("batch", "run")]
    for knob in knobs:
        group.removeKnob(knob)
    group.addKnob(nuke.Text_Knob("run_divider", ""))
    for knob in knobs:
        group.addKnob(knob)


def expose_controls(group, created, controls):
    widgets = {}
    widget_targets = {}
    for label, targets in controls:
        knobs = [widget_knob(created.get(key), widget) for key, widget in targets]
        knobs = [knob for knob in knobs if knob]
        if not knobs:
            continue
        name = expose_knob(group, knobs[0], label, widgets)
        widget_targets[name] = [
            [relative_path(group, knob.node()), knob.name()] for knob in knobs[1:]
        ]
    widget_targets = {key: value for key, value in widget_targets.items() if value}
    if widget_targets:
        write_metadata(group, "comfyui_widget_targets", widget_targets)
        enable_widget_sync(group)
    if widgets:
        move_run_controls_to_end(group)


def create_workflow_gizmo(data, definitions, not_installed):
    flat = flatten_workflow(data, definitions)
    gizmo_path = os.path.join(COMFYUI2NUKE, "nodes/ComfyUI/ComfyUIGizmo.nk")
    group = nuke.nodePaste(gizmo_path)
    group.setSelected(False)
    context = nuke.thisGroup()
    group.begin()
    try:
        write = nuke.toNode("Write") or nuke.toNode("WriteImage")
        run = nuke.toNode("Run")
        output = nuke.toNode("Output1")
        if not write or not run or not output:
            raise ValueError(
                "ComfyUIGizmo must contain Write (or WriteImage), Run and Output1"
            )
        for child in list(nuke.allNodes("Input")):
            nuke.delete(child)
        write.setInput(0, None)
        run.setInput(0, write)
        output.setInput(0, run)
        created, _ = build_flat_graph(flat, not_installed)
        main = connect_main_output(flat, created, write, run)
        expose_controls(group, created, flat["controls"].values())
        arrange_candidates(nuke.allNodes())
    finally:
        group.end()
        context.begin()
    name = flat["names"].get(main)
    if name:
        group.setName(normalize_nodename(name))
    return group
