import json

import nuke  # type: ignore


def read_metadata(node, name):
    knob = node.knob(name)
    return json.loads(knob.value()) if knob else {}


def write_metadata(node, name, data):
    knob = node.knob(name)
    if not knob:
        knob = nuke.String_Knob(name)
        knob.setVisible(False)
        node.addKnob(knob)
    knob.setValue(json.dumps(data))


def resolve_workflow_input(node, index, ignore_disabled=True):
    slot = read_metadata(node, "comfyui_import_links").get(str(index))
    current = node.input(index)
    visited = set()
    while current and current not in visited:
        visited.add(current)
        if current.Class() == "Input":
            index = int(current["number"].value())
            parent = current.parent()
            slot = read_metadata(parent, "comfyui_import_links").get(str(index))
            current = parent.input(index)
            continue
        disabled = current.knob("disable")
        bypassed = ignore_disabled and disabled and disabled.value()
        subgraph = read_metadata(current, "comfyui_subgraph")
        if subgraph and not bypassed:
            outputs = subgraph.get("outputs", [])
            output_index = slot if slot is not None else 0
            if not 0 <= output_index < len(outputs) or not outputs[output_index]:
                return None, None
            name, slot = outputs[output_index]
            current = next(
                (
                    child
                    for child in current.nodes()
                    if read_metadata(child, "comfyui_output_id").get("id") == name
                ),
                None,
            )
            continue
        index = None
        if current.Class() == "Dot" or bypassed or current.knob("override_settings"):
            index = 0
        elif current.Class() == "Switch" and current.knob("switch_any"):
            index = int(current["which"].value())
        elif current.Class() == "Group" and current.knob("null_input"):
            return None, None
        if index is None:
            return current, slot
        slot = read_metadata(current, "comfyui_import_links").get(str(index))
        current = current.input(index)
    return None, None
