import nuke  # type: ignore
from ...nuke_util.nuke_util import selected_node, get_output_nodes, get_input_nodes, transfer_knobs
from ..update_menu import create_comfyui_node, update_menu
from ..nodes import get_node_data


def reload_node():
    nodes = selected_node(False)

    if not nodes:
        nuke.message('Select at least 1 ComfyUI node!')
        return

    nodes[0].parent().begin()
    [n.setSelected(False) for n in nuke.selectedNodes()]

    for node in nodes:
        data = get_node_data(node)
        if not data:
            continue

        name = node.name()
        node.setName('_aux_')
        class_type = data['class_type']

        update_menu()

        with node.parent():
            new_node = create_comfyui_node(class_type, False)
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
