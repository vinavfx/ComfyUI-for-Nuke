# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ...nuke_util.nuke_util import selected_node
from ..nodes import get_node_data, save_node_data


def knob_to_input():

    node = selected_node()
    if not node:
        return

    data = get_node_data(node)
    if not data:
        nuke.message('Must be a ComfyUI node !')
        return

    panel = nuke.Panel('Knob to Input ({})'.format(node.name()))

    knobs = []
    for knob in data['knobs_order']:
        if not knob in data['knobs_class']:
            continue
        _class = data['knobs_class'][knob]
        knobs.append((knob, knob[:-1], _class))

    for knob, knob_name, _ in knobs:
        if any(v.get('name') == knob_name for v in data['inputs']):
            panel.addBooleanCheckBox(knob_name, True)
        else:
            panel.addBooleanCheckBox(knob_name, False)

    if not panel.show():
        return

    for knob, knob_name, _class in knobs:
        value = panel.value(knob_name)

        knob_data = {
            'opt': False,
            'outputs': [_class],
            'name': knob_name
        }

        exists_konb = any(i.get('name') == knob_name for i in data['inputs'])

        if value:
            if not exists_konb:
                data['inputs'].append(knob_data)
                _knob = node.knob(knob)
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
            _knob.setName(knob)
            _knob.setVisible(True)
            node.knob('label').setValue('')

    save_node_data(node, data)
