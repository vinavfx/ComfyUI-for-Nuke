# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
from ..python_util.util import jread
from .update_menu import create_comfyui_node, remove_signs, update_menu
from .queue_prompt import error_node_style
from .nodes import get_node_data
from .connection import convert_to_utf8
from ..env import NUKE_USER


def center_nodes(nodes):
    min_x = min(node['xpos'].value() for node in nodes)
    min_y = min(node['ypos'].value() for node in nodes)

    for node in nodes:
        new_x = node['xpos'].value() - min_x
        new_y = node['ypos'].value() - min_y
        node.setXYpos(int( new_x ), int( new_y ))


def import_workflow():
    workflow_path = nuke.getFilename('Workflow', '*.json')
    if not workflow_path:
        return

    update_menu()
    data = jread(workflow_path)

    [n.setSelected(False) for n in nuke.selectedNodes()]

    create_nodes = {}
    not_installed = []
    nodes = []

    for attrs in data['nodes']:
        node = create_comfyui_node(attrs['type'], inpanel=False)

        if not node:
            node = nuke.createNode('NoOp', inpanel=False)
            node.setName(remove_signs(attrs['type']))
            error_node_style(node.fullName(), True, 'Node not installed !')
            not_installed.append(attrs['type'])

        create_nodes[attrs['id']] = (node, attrs)
        nodes.append(node)

        node.setSelected(False)
        xpos, ypos = attrs['pos']
        node.setXYpos(int(xpos/2), int(ypos/2))

    center_nodes([n[0] for n in create_nodes.values()])

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
        if not node_data:
            continue

        knobs_order = node_data['knobs_order']
        values = []

        for value in attrs.get('widgets_values', []):
            if value in ['fixed', 'increment', 'decrement', 'randomize']:
                if any('seed' in s for s in knobs_order):
                    randomize_knob = node.knob('randomize')
                    if randomize_knob:
                        randomize_knob.setValue(not value == 'fixed')
                    continue
            values.append(value)

        for i, value in enumerate(values):
            if i >= len(knobs_order):
                continue

            value = convert_to_utf8(value)
            knob = node.knob(knobs_order[i])

            if type(value) == int:
                value = value if value < 1e9 else 1e9
                knob.setValue(int(value))
            else:
                knob.setValue(value)

        for i, idata in enumerate(attrs.get('inputs', {})):
            link = idata['link']
            onode = find_node_link(link)
            node.setInput(i, onode)

        if 'Save' in attrs['type']:
            queue_prompt_nk = os.path.join(
                NUKE_USER, 'nuke_comfyui/nodes/ComfyUI/QueuePrompt.nk')
            queue_prompt = nuke.nodePaste(queue_prompt_nk)
            queue_prompt.setInput(0, node)
            queue_prompt.setSelected(False)
            queue_prompt.setXYpos(node.xpos(), node.ypos() + 25)
            nodes.append(queue_prompt)

    [n.setSelected(True) for n in nodes]

    if not_installed:
        nodes_list = '\n'.join(not_installed)
        nuke.message(
            'You need to install these nodes in ComfyUI:\n\n' + nodes_list)
