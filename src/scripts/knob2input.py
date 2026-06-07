# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ...nuke_util.nuke_util import selected_node
from ..nodes import get_node_data, save_node_data


def get_swapped_knobs(node):
    data = get_node_data(node)
    if not data:
        nuke.message('Must be a ComfyUI node !')
        return None, None

    swapped_knobs = {}

    for nuke_knob_name in data.get('knobs_order', []):
        if not nuke_knob_name in data.get('knobs_class', {}):
            continue

        knob_name = nuke_knob_name[:-1]

        if any(v.get('name') == knob_name for v in data['inputs']):
            swapped_knob = True
        else:
            swapped_knob = False

        swapped_knobs[knob_name] = {
            'class': data['knobs_class'][nuke_knob_name],
            'swapped_knob': swapped_knob
        }

    return swapped_knobs, data


def knob_to_input():
    node = selected_node()
    if not node:
        return

    panel = nuke.Panel('Knob to Input ({})'.format(node.name()))

    swapped_knobs, data = get_swapped_knobs(node)
    if not swapped_knobs:
        return

    for knob_name, knob in swapped_knobs.items():
        panel.addBooleanCheckBox(knob_name, knob['swapped_knob'])

    if not panel.show():
        return

    for knob_name, knob in swapped_knobs.items():
        swapped_knobs[knob_name]['swapped_knob'] = panel.value(knob_name)

    convert_knobs(node, data, swapped_knobs)


def convert_knobs(node, data, swapped_knobs):
    for knob_name, knob in swapped_knobs.items():
        nuke_knob_name = knob_name + '_'

        knob_data = {
            'opt': False,
            'outputs': [knob['class']],
            'name': knob_name
        }

        exists_konb = any(i.get('name') == knob_name for i in data['inputs'])

        if knob['swapped_knob']:
            if not exists_konb:
                data['inputs'].append(knob_data)
                _knob = node.knob(nuke_knob_name)
                if _knob is None:
                    continue
                _knob.setName(knob_name + '_hide')
                _knob.setVisible(False)
                node.begin()
                input_node = nuke.createNode('Input', inpanel=False)
                input_node.setSelected(False)
                input_node.setName(knob_name)
                node.end()

        elif exists_konb:
            node.begin()
            nuke.delete(nuke.toNode(knob_name))
            node.end()
            data['inputs'] = [i for i in data['inputs']
                              if i.get('name') != knob_name]

            _knob = node.knob(knob_name + '_hide')
            if _knob is None:
                continue
            _knob.setName(nuke_knob_name)
            _knob.setVisible(True)
            node.knob('label').setValue('')

    save_node_data(node, data)
