# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import re
import textwrap
from copy import deepcopy

import nuke  # type: ignore

from ..nuke_util.nuke_util import set_hex_color
from ..nuke_util.python_util import jread
from ..settings import COMFYUI2NUKE
from .common import show_message, wait_for_comfyui
from .connection import convert_to_utf8
from .nodes import get_node_data, save_node_data
from .run import error_node_style
from .scripts.knob2input import convert_knobs
from .update_menu import create_comfyui_node, normalize_nodename, update_menu
from .workflow_connections import read_metadata, write_metadata
from .workflow_templates import select_template


def center_nodes(nodes):
    if not nodes:
        return
    min_x = min(node.xpos() for node in nodes)
    min_y = min(node.ypos() for node in nodes)
    for node in nodes:
        node.setXYpos(node.xpos() - min_x, node.ypos() - min_y)


def workflow_links(data):
    keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
    return {
        str(link["id"] if isinstance(link, dict) else link[0]): (
            link if isinstance(link, dict) else dict(zip(keys, link))
        )
        for link in data.get("links", [])
    }


def import_workflow():
    panel = nuke.Panel("Import Workflow")
    panel.addEnumerationPulldown("Source", "JSON\\ file ComfyUI\\ templates")
    if not panel.show():
        return
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
            data = jread(workflow_path)
        except (OSError, ValueError) as error:
            show_message("Could not read the workflow: {}".format(error))
            return
    if data is not None:
        import_workflow_data(data)


def import_workflow_data(data):
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        show_message("Incompatible workflow, perhaps exported from 'Export(API)'.")
        return
    if wait_for_comfyui(lambda: import_workflow_data(data)):
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
    try:
        _, nodes = build_graph(data, definitions, not_installed)
        for node in nodes:
            node.setSelected(True)
    except (KeyError, ValueError, TypeError, RuntimeError) as error:
        show_message(
            "Could not import the workflow: {}. Use Undo to remove it.".format(error)
        )
    finally:
        undo.end()
    if not_installed:
        show_message(
            "You need to install these nodes in ComfyUI:\n\n"
            + "\n".join(sorted(not_installed))
        )


def knob_for_input(node, name):
    data = get_node_data(node)
    names = data.get("knobs_input_names", {})
    knob_name = next((key for key, value in names.items() if value == name), name + "_")
    promoted = read_metadata(node, "comfyui_subgraph").get("widgets", {})
    return node.knob(promoted.get(name, knob_name))


def set_widget_value(node, knob, value):
    if knob is None or value is None:
        return
    try:
        if knob.name() == "randomize":
            value = value != "fixed"
        if type(value) is int:
            value = min(value, 999999999)
        knob.setValue(convert_to_utf8(value))
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


def note_width(attrs):
    size = attrs.get("size", [560, 0])
    try:
        width = size.get("0", 560) if isinstance(size, dict) else size[0]
        return max(24, min(100, int(float(width) / 14)))
    except (IndexError, TypeError, ValueError):
        return 40


def clean_markdown(text):
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)[*_]([^\n*_]+)[*_](?!\w)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def format_note(text, width):
    lines = []
    for line in clean_markdown(text).splitlines():
        if not line.strip():
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                line,
                width=width,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return "\n".join(lines).strip()


def create_workflow_node(attrs, not_installed):
    node_type = attrs["type"]
    node = create_comfyui_node(node_type, inpanel=False)
    if node_type in ("Note", "MarkdownNote"):
        node = nuke.createNode("StickyNote", inpanel=False)
        values = attrs.get("widgets_values") or [""]
        text = str(convert_to_utf8(values[0]))
        node["label"].setValue(format_note(text, note_width(attrs)))
    elif node_type in ("Reroute", "easy getNode", "easy setNode"):
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
    subgraph = read_metadata(node, "comfyui_subgraph")
    if subgraph:
        names = subgraph.get("inputs", [])
        return names.index(item["name"]) if item["name"] in names else None
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


def build_graph(data, definitions, not_installed, boundary=None, stack=()):
    created = {}
    nodes = []
    links = workflow_links(data)
    for attrs in data.get("nodes", []):
        definition = definitions.get(attrs["type"])
        if definition:
            if attrs["type"] in stack:
                raise ValueError("Recursive subgraph definition")
            node = create_subgraph(
                attrs, definition, definitions, not_installed, stack + (attrs["type"],)
            )
        else:
            node = create_workflow_node(attrs, not_installed)
        created[str(attrs["id"])] = node
        nodes.append(node)
        node.setSelected(False)
        if not node["tile_color"].value():
            set_hex_color(node, attrs.get("bgcolor"))
        pos = attrs.get("pos", [0, 0])
        x, y = (pos["0"], pos["1"]) if isinstance(pos, dict) else pos
        node.setXYpos(int(x / 2), int(y / 2))
    for attrs in data.get("nodes", []):
        node = created[str(attrs["id"])]
        for fallback, item in enumerate(attrs.get("inputs", [])):
            index = input_index(node, item, fallback)
            if index is None:
                continue
            link = links.get(str(item.get("link")))
            if not link:
                node.setInput(index, None)
                continue
            source = created.get(str(link["origin_id"]))
            input_id = data.get("inputNode", {}).get("id", -10)
            if source is None and boundary and str(link["origin_id"]) == str(input_id):
                source = boundary.get(link["origin_slot"])
            if source:
                connect_link(
                    node,
                    index,
                    source,
                    link["origin_slot"] if source in created.values() else None,
                )
        if attrs["type"] == "easy getNode":
            title = attrs.get("title", attrs["type"])
            source = next(
                (
                    created[str(other["id"])]
                    for other in data["nodes"]
                    if other["type"] == "easy setNode" and other.get("title") == title
                ),
                None,
            )
            node.setInput(0, source)
            node["hide_input"].setValue(True)
        if not stack and get_node_data(node).get("output_node"):
            run_path = os.path.join(COMFYUI2NUKE, "nodes/ComfyUI/Run.nk")
            run = nuke.nodePaste(run_path)
            run.setInput(0, node)
            run.setXYpos(node.xpos(), node.ypos() + 25)
            run.setSelected(False)
            nodes.append(run)
    for attrs in data.get("groups", []):
        backdrop = nuke.createNode("BackdropNode", inpanel=False)
        backdrop.setName("GROUP")
        backdrop["label"].setValue(convert_to_utf8(attrs.get("title", "")))
        x, y, width, height = attrs["bounding"]
        backdrop["bdwidth"].setValue(width / 2)
        backdrop["bdheight"].setValue(height / 2)
        backdrop.setXYpos(int(x / 2), int(y / 2))
        backdrop["z_order"].setValue(0)
        backdrop["note_font_size"].setValue(30)
        set_hex_color(backdrop, attrs.get("color"))
        backdrop.setSelected(False)
        nodes.append(backdrop)
    center_nodes(nodes)
    return created, nodes


def subgraph_boundary(definition, attrs):
    links = workflow_links(definition)
    external = {item["name"]: item for item in attrs.get("inputs", [])}
    input_id = definition.get("inputNode", {}).get("id", -10)
    sockets = []
    promoted = []
    for slot, item in enumerate(definition.get("inputs", [])):
        host = external.get(item["name"])
        is_socket = host and (not host.get("widget") or host.get("link") is not None)
        targets = [
            link
            for link in links.values()
            if str(link["origin_id"]) == str(input_id) and link["origin_slot"] == slot
        ]
        if is_socket:
            sockets.append((slot, item))
        else:
            promoted.append((item, targets))
            target_ids = {str(link["id"]) for link in targets}
            for child in definition.get("nodes", []):
                for child_input in child.get("inputs", []):
                    if str(child_input.get("link")) in target_ids:
                        child_input["link"] = None
    return sockets, promoted


def sync_widget_targets(group, widget_targets):
    for source_name, targets in widget_targets.items():
        source = group.knob(source_name)
        if not source:
            continue
        for target_path, target_name in targets:
            target = nuke.toNode(group.fullName() + "." + target_path)
            target_knob = target.knob(target_name) if target else None
            if target_knob:
                target_knob.setValue(source.value())


def enable_widget_sync(group):
    callback = (
        "import json\n"
        "node = nuke.thisNode()\n"
        "knob = nuke.thisKnob()\n"
        "metadata = json.loads(node['comfyui_subgraph'].value())\n"
        "targets = metadata.get('widget_targets', {}).get(knob.name(), [])\n"
        "for target_path, target_name in targets:\n"
        "    target = nuke.toNode(node.fullName() + '.' + target_path)\n"
        "    target_knob = target.knob(target_name) if target else None\n"
        "    if target_knob:\n"
        "        target_knob.setValue(knob.value())"
    )
    existing = group["knobChanged"].value().rstrip()
    group["knobChanged"].setValue(existing + ("\n" if existing else "") + callback)


def expose_knob(group, knob, label, widgets):
    if not knob:
        return
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
    prefix_length = len(group.fullName()) + 1
    target_path = knob.node().fullName()[prefix_length:]
    link.makeLink(target_path, knob.name())
    group.addKnob(link)
    widgets[label] = name
    return name


def create_subgraph(attrs, definition, definitions, not_installed, stack):
    definition = deepcopy(definition)
    sockets, promoted = subgraph_boundary(definition, attrs)
    gizmo_path = os.path.join(COMFYUI2NUKE, "nodes/ComfyUI/ComfyUIGizmo.nk")
    group = nuke.nodePaste(gizmo_path)
    group.setName(
        normalize_nodename(definition.get("name") or attrs.get("title", "Subgraph"))
    )
    group.setSelected(False)
    boundary = {}
    group.begin()
    try:
        write_image = nuke.toNode("WriteImage")
        run = nuke.toNode("Run")
        output = nuke.toNode("Output1")
        if not write_image or not run or not output:
            raise ValueError("ComfyUIGizmo must contain WriteImage, Run and Output1")
        for child in list(nuke.allNodes("Input")):
            nuke.delete(child)
        for index, (slot, item) in enumerate(sockets):
            node = nuke.createNode("Input", inpanel=False)
            node.setName(normalize_nodename(item["name"]))
            node["number"].setValue(index)
            node.setXYpos(index * 140, -100)
            node.setSelected(False)
            boundary[slot] = node
        created, _ = build_graph(
            definition, definitions, not_installed, boundary, stack
        )
        links = workflow_links(definition)
        output_id = definition.get("outputNode", {}).get("id", -20)
        outputs = []
        for slot, item in enumerate(definition.get("outputs", [])):
            link = next(
                (
                    link
                    for link in links.values()
                    if str(link["target_id"]) == str(output_id)
                    and link["target_slot"] == slot
                ),
                None,
            )
            source = created.get(str(link["origin_id"])) if link else None
            output_slot = link["origin_slot"] if link else None
            if link and str(link["origin_id"]) == str(
                definition.get("inputNode", {}).get("id", -10)
            ):
                source = boundary.get(link["origin_slot"])
                output_slot = None
            outputs.append([source.name(), output_slot] if source else None)
            if source:
                write_metadata(source, "comfyui_output_id", {"id": source.name()})
            if slot == 0:
                if source:
                    connect_link(write_image, 0, source, output_slot)
                run.setInput(0, write_image)
                output.setInput(0, run)
                output.setSelected(False)
        widgets = {}
        widget_targets = {}
        exposed = set()
        for item, targets in promoted:
            for link in targets:
                target = created.get(str(link["target_id"]))
                child = next(
                    (
                        child
                        for child in definition["nodes"]
                        if str(child["id"]) == str(link["target_id"])
                    ),
                    None,
                )
                if not target or not child:
                    continue
                target_input = child.get("inputs", [])[link["target_slot"]]
                knob = knob_for_input(
                    target,
                    target_input.get("widget", {}).get("name", target_input["name"]),
                )
                key = (str(child["id"]), target_input["name"])
                if knob:
                    exposed.add(key)
                    if item["name"] not in widgets:
                        expose_knob(group, knob, item["name"], widgets)
                    else:
                        prefix_length = len(group.fullName()) + 1
                        target_path = knob.node().fullName()[prefix_length:]
                        source_name = widgets[item["name"]]
                        widget_targets.setdefault(source_name, []).append(
                            [target_path, knob.name()]
                        )
        proxies = attrs.get("properties", {}).get("proxyWidgets", [])
        proxy_knobs = []
        for node_id, widget_name in proxies:
            target = created.get(str(node_id))
            if not target:
                proxy_knobs.append(None)
                continue
            knob = (
                target.knob("randomize")
                if widget_name == "control_after_generate"
                else knob_for_input(target, widget_name)
            )
            proxy_knobs.append((target, knob))
            if (str(node_id), widget_name) not in exposed:
                expose_knob(group, knob, widget_name, widgets)
        write_metadata(
            group,
            "comfyui_subgraph",
            {
                "inputs": [item["name"] for _, item in sockets],
                "outputs": outputs,
                "widgets": widgets,
                "widget_targets": widget_targets,
            },
        )
        if widget_targets:
            enable_widget_sync(group)
        values = attrs.get("widgets_values") or []
        if proxies:
            for target_knob, value in zip(proxy_knobs, values):
                if target_knob:
                    target, knob = target_knob
                    set_widget_value(target, knob, value)
        else:
            for name, value in zip(widgets.values(), values):
                set_widget_value(group, group.knob(name), value)
        sync_widget_targets(group, widget_targets)
    finally:
        group.end()
    return group
