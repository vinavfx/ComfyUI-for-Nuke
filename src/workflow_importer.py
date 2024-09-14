# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import textwrap
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
        node.setXYpos(int(new_x), int(new_y))


def import_workflow():
    workflow_path = nuke.getFilename('Workflow', '*.json')
    if not workflow_path:
        return

    if not update_menu():
        return

    data = jread(workflow_path)
    [n.setSelected(False) for n in nuke.selectedNodes()]

    create_nodes = {}
    not_installed = []
    nodes = []

    for attrs in data['nodes']:
        node = create_comfyui_node(attrs, inpanel=False)

        if attrs['type'] == 'Note':
            node = nuke.createNode('BackdropNode', inpanel=False)
            text = str(convert_to_utf8(attrs['widgets_values'][0]))
            formatted_note = '\n'.join(textwrap.wrap(text, width=40))
            node.knob('label').setValue(formatted_note + '\n\n')
            node.knob('bdwidth').setValue(attrs['size']['0'])
            node.knob('bdheight').setValue(attrs['size']['1'])
            node.knob('z_order').setValue(10)

        elif attrs['type'] in ('Reroute', 'easy getNode', 'easy setNode'):
            node = nuke.createNode('Dot', inpanel=False)
            if attrs['type'] in ('easy getNode', 'easy setNode'):
                node.setName(attrs['title'])
                node.knob('label').setValue(f"Get/Set \n {attrs['title']}")

        elif not node:
            node = nuke.createNode('NoOp', inpanel=False)
            node.setName(remove_signs(attrs['type']))
            error_node_style(node.fullName(), True, 'Node not installed !')
            not_installed.append(attrs['type'])

        create_nodes[attrs['id']] = (node, attrs)
        nodes.append(node)
        node.setSelected(False)

        pos = attrs['pos']

        if type(pos) == list:
            xpos, ypos = attrs['pos']
        else:
            xpos = attrs['pos']['0']
            ypos = attrs['pos']['1']

        node.setXYpos(int(xpos/2), int(ypos/2))

    for attrs in data['groups']:
        node = nuke.createNode('BackdropNode', inpanel=False)
        text = str(convert_to_utf8(attrs['title']))
        formatted_note = '\n'.join(textwrap.wrap(text, width=40))
        node.knob('label').setValue(formatted_note + '\n\n')
        node.knob('bdwidth').setValue(attrs['bounding'][2]/2)
        node.knob('bdheight').setValue(attrs['bounding'][3]/2)
        node.setXYpos(int(attrs['bounding'][0]/2), int(attrs['bounding'][1]/2))
        node.knob('z_order').setValue(0) 
        node.knob('note_font_size').setValue(100) 
        hex_color = attrs['color']
        node.knob('tile_color').setValue(hex2dec(hex_color))

        nodes.append(node)
        node.setSelected(False)

    if not nodes:
        return

    center_nodes(nodes)

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
        if attrs['type'] in ('Reroute', 'easy getNode', 'easy setNode'):
            knobs_order = []
            if attrs['type'] in ('easy getNode', 'easy setNode'):
                node_name = 'S' + attrs['title'][1:]
                node.setInput(i, nuke.toNode(node_name))
                if attrs['type'] in ('easy getNode'):
                    node.knob('hide_input').setValue(True)
        else:
            node_data = get_node_data(node)
            if not node_data:
                continue

            knobs_order = node_data['knobs_order']

        widgets_values = attrs.get('widgets_values')
        values = []

        if type(widgets_values) == list:
            for value in widgets_values:
                if value in ['fixed', 'increment', 'decrement', 'randomize']:
                    if any('seed' in s for s in knobs_order):
                        randomize_knob = node.knob('randomize')
                        if randomize_knob:
                            randomize_knob.setValue(not value == 'fixed')
                        continue
                values.append(value)
        else:
            for key in knobs_order:
                values.append(widgets_values[key[:-1]])

        if not len(values) == len(knobs_order):
            values = [v for v in values if v is not None]

        for i, value in enumerate(values):
            if i >= len(knobs_order):
                continue

            value = convert_to_utf8(value)
            knob = node.knob(knobs_order[i])

            if type(value) == int:
                value = value if value < 1e9 else 1e9
                knob.setValue(int(value))
            else:
                try:
                    knob.setValue(value)
                except:
                    nuke.message('Could not set the knob "{}" value for this node "{}" !'.format(
                        knob.name(), node.name()))

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


def hex2dec(hex_string)->int:
    """
        Return the integer value of a hexadecimal string
        Maybe this can live in nuke_util module?
    """
    if hex_string.startswith("#"):
        hex_string = hex_string[1:]
    if len(hex_string) == 3:
        hex_string = hex_string[0] + hex_string[0] + hex_string[1] + hex_string[1] + hex_string[2] + hex_string[2]
    if len(hex_string) == 6:
        hex_string += "FF"
    return int(hex_string, 16)
