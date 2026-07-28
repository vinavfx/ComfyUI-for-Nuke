import nuke  # type: ignore
from ...nuke_util.nuke_util import selected_node, get_output_nodes, get_input_nodes, transfer_knobs
from ..update_menu import create_comfyui_node, update_menu
from ..nodes import get_node_data, save_node_data
from .knob2input import convert_knobs, get_swapped_knobs


def reload_node():
    nodes = selected_node(False)

    if not nodes:
        nuke.message("Select at least 1 ComfyUI node!")
        return

    nodes[0].parent().begin()
    [n.setSelected(False) for n in nuke.selectedNodes()]

    if update_menu(lambda: reload_node_action(nodes)):
        return

    reload_node_action(nodes)


def reload_node_action(nodes):
    updated_nodes = []
    not_updated_nodes = []

    for node in nodes:
        data = get_node_data(node)
        if not data:
            continue

        name = node.name()
        node.setName("_aux_")
        class_type = data["class_type"]

        swapped_knobs, _ = get_swapped_knobs(node)
        force_outputs = {n["name"]: n["force_output"] for n in data["inputs"] if "force_output" in n}

        with node.parent():
            new_node = create_comfyui_node(class_type, False)

            if new_node:
                updated_nodes.append(name)
            else:
                not_updated_nodes.append(class_type)
                node.setName(name)
                continue

            convert_knobs(new_node, get_node_data(new_node), swapped_knobs)

            new_data = get_node_data(new_node)
            for n in new_data["inputs"]:
                if n["name"] in force_outputs:
                    n["force_output"] = force_outputs[n["name"]]
            save_node_data(new_node, new_data)

            transfer_knobs(node, new_node, transfer_all=True)

            if new_node:
                new_node.setName(name)
                new_node.setSelected(False)

                for i, onode in get_output_nodes(node):
                    onode.setInput(i, new_node)

                for i, inode in get_input_nodes(node):
                    new_node.setInput(i, inode)

                new_node.setXYpos(node.xpos(), node.ypos())

            nuke.delete(node)

    if updated_nodes or not_updated_nodes:
        msg = ""
        if updated_nodes:
            msg = "{} reloaded nodes:\n".format(len(updated_nodes))
            msg += "\n".join(updated_nodes)

        if not_updated_nodes:
            msg += "\n\n{} nodes not installed:\n".format(len(not_updated_nodes))
            msg += "\n".join(not_updated_nodes)

        nuke.message(msg)
    else:
        nuke.message("Select a ComfyUI node!")
