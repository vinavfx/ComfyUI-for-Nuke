# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import os
import json
from ..nodes import extract_data
from ...nuke_util.nuke_util import selected_node
from ...nuke_util.python_util import jwrite
from ..common import update_images_and_mask_inputs, get_settings


def api_to_workflow(api):
    id_map = {name: i for i, name in enumerate(api, 1)}
    wf = {
        "last_node_id": len(api),
        "last_link_id": 0,
        "nodes": [],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }
    lk_id = 1

    for name, body in api.items():
        attrs = body.get("nuke_attrs", {})
        xpos = attrs.get("xpos", 0) * 3
        ypos = attrs.get("ypos", 0) * 3
        tile_color = attrs.get("tile_color")

        hex_color = (
            f"#{int((tile_color >> 24) & 0xFF):02x}"
            f"{int((tile_color >> 16) & 0xFF):02x}"
            f"{int((tile_color >> 8) & 0xFF):02x}"
            if tile_color
            else "#4d4d4d"
        )

        n_id = id_map[name]
        ins, w_vals = [], []

        for k, v in body.get("inputs", {}).items():
            if isinstance(v, list) and v and isinstance(v[0], str) and v[0] in id_map:
                wf["links"].append([lk_id, id_map[v[0]], v[1], n_id, len(ins), "IMAGE"])
                ins.append({"name": k, "type": "IMAGE", "link": lk_id})
                lk_id += 1
            else:
                w_vals.append(v)
                if "seed" in k:
                    w_vals.append("fixed")

        node_data = {
            "id": n_id,
            "type": body.get("class_type", ""),
            "pos": [xpos, ypos],
            "order": n_id,
            "mode": 0,
            "inputs": ins,
            "outputs": [],
            "properties": {"NodeData": {"title": name}},
            "widgets_values": w_vals,
        }

        if hex_color:
            node_data["color"] = node_data["bgcolor"] = hex_color

        wf["nodes"].append(node_data)

    wf["last_link_id"] = lk_id - 1

    for lk in wf["links"]:
        for n in wf["nodes"]:
            if n["id"] == lk[1] and lk[2] < len(n["outputs"]):
                n["outputs"][lk[2]]["links"].append(lk[0])

    return json.dumps(wf, indent=4)


def copy_workflow():
    data = get_workflow()
    if not data:
        return

    workflow, settings = data
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    xclip = os.path.join(root, "bin/xclip")

    os.system(
        "echo '{}' | {} -selection clipboard".format(api_to_workflow(workflow), xclip)
    )

    url = json.loads(settings["URL"])[0]

    if nuke.ask("Workflow copied to clipboard\nOpen ComfyUI and paste ?"):
        os.system("xdg-open http://" + url)


def get_workflow():
    node = selected_node()
    if not node:
        return

    if node.knob("comfyui_gizmo"):
        node.begin()
        node = nuke.toNode("Run")

    elif not node.knob("run"):
        nuke.message("Select the 'Run' node")
        return

    settings = get_settings(node)
    update_images_and_mask_inputs()
    data, _, _ = extract_data(node, settings)

    return data, settings


def export_workflow():
    data = get_workflow()
    if not data:
        return
    data = data[0]

    workflow = nuke.getFilename(
        "Export Workflow",
        "*.json",
        os.path.join(os.path.expanduser("~"), "Desktop/workflow.json"),
        type="save",
    )

    if not workflow:
        return

    workflow = workflow if "json" in workflow else workflow + ".json"
    jwrite(workflow, data)

    nuke.message("Workflow Saved: " + workflow)
