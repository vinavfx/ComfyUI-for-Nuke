# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ...nuke_util.nuke_util import get_input, selected_node
from ..nodes import get_node_data, requires_force_output, save_node_data



def force_output(node=None):
    if not node:
        node = selected_node()

    if not node:
        return

    data = get_node_data(node)

    p = nuke.Panel('Force Output ({})'.format(node.name()))
    items = []

    for i in range(node.inputs()):
        inode = get_input(node, i, active_switch=True)
        if not inode:
            continue

        inputs_data = data['inputs'][i]
        input_class = inputs_data['outputs'][0]
        force_output = inputs_data.get('force_output')

        inputs = list(reversed(nuke.allNodes(filter='Input', group=node)))
        input_node = inputs[i]
        label = input_node.name() + ' : ' + inode.name()

        dst_node_data = get_node_data(inode)
        if not dst_node_data:
            continue

        outputs = dst_node_data['outputs']
        if not requires_force_output(outputs, input_class):
            data['inputs'][i].pop('force_output', None)
            continue

        if not 'output_name' in dst_node_data:
            nuke.message('{} obsolete node, generate node again'.format(dst_node_data['class_type']))
            return

        output_name = dst_node_data['output_name']

        outputs_items = ' '.join([n.replace(' ', '\\ ') for n in output_name])
        outputs_items = '- ' + outputs_items

        if not force_output == None:
            outputs_items = output_name[force_output] + ' ' + outputs_items

        p.addEnumerationPulldown(label, outputs_items)
        items.append((label, output_name, i))

    save_node_data(node, data)

    if not items:
        nuke.message('All outputs are different, there is no need to force it')
        node.knob('label').setValue('')
        return

    if not p.show():
        return

    force_outputs = ''
    for label, output_name, input_index in items:
        value = p.value(label)

        if value == '-':
            data['inputs'][input_index].pop('force_output', None)
            continue

        output_index = output_name.index(value)
        input_name = data['inputs'][input_index]['name']

        data['inputs'][input_index]['force_output'] = output_index
        force_outputs += '{} -> {}\n'.format(input_name, value)

    if force_outputs:
        node.knob('label').setValue(
            '<font color="green" size=1>{}</font>'.format(force_outputs[:-1]))
    else:
        node.knob('label').setValue('')

    save_node_data(node, data)
