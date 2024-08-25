# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..python_util.util import jread
from .update_menu import create_comfyui_node, remove_signs, update_menu
from .queue_prompt import error_node_style
from .nodes import get_node_data
from .connection import convert_to_utf8


def import_workflow():
    workflow_path = nuke.getFilename('Workflow', '*.json')
    if not workflow_path:
        return

    update_menu()
    data = jread(workflow_path)

    [n.setSelected(False) for n in nuke.selectedNodes()]

    create_nodes = {}

    for attrs in data['nodes']:
        node = create_comfyui_node(attrs['type'], inpanel=False)

        if node:
            create_nodes[attrs['id']] = (node, attrs)

        else:
            node = nuke.createNode('NoOp', inpanel=False)
            node.setName(remove_signs(attrs['type']))
            error_node_style(node.fullName(), True, 'Node not installed !')

        node.setSelected(False)
        xpos, ypos = attrs['pos']
        node.setXYpos(int(xpos/2), int(ypos/2))

    def find_node_link(link):
        if not link:
            return

        for node, attrs in create_nodes.values():
            for odata in attrs.get('outputs', {}):
                links = odata['links']
                if not links:
                    continue

                if link in links:
                    return node

    for node, attrs in create_nodes.values():
        node_data = get_node_data(node)
        knobs_order = node_data['knobs_order']

        for i, value in enumerate(attrs.get('widgets_values', [])):
            if i >= len(knobs_order):
                continue

            value = convert_to_utf8(value)
            knob = node.knob(knobs_order[i])
            knob.setValue(value)

        for i, idata in enumerate(attrs.get('inputs', {})):
            link = idata['link']
            onode = find_node_link(link)
            node.setInput(i, onode)
