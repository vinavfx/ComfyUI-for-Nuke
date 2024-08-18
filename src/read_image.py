# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore

from ..nuke_util.nuke_util import get_input
from ..settings import COMFYUI_DIR


def create_read(queue_prompt_node):
    output_node = get_input(queue_prompt_node, 0)
    if not output_node:
        return

    comfyui_output = os.path.join(COMFYUI_DIR, 'output')
    filename_prefix_knob = output_node.knob('filename_prefix_')

    if filename_prefix_knob:
        filename_prefix = filename_prefix_knob.value()
    else:
        return

    filenames = nuke.getFileNameList(comfyui_output)
    filename = next((fn for fn in filenames if filename_prefix in fn), None)

    if not filename:
        return

    name = '{}Read'.format(queue_prompt_node.name())
    read = nuke.toNode(name)
    if not read:
        read = nuke.createNode('Read', inpanel=False)

    read.setName(name)
    read.knob('file').fromUserText(os.path.join(comfyui_output, filename))
    read.setXYpos(queue_prompt_node.xpos(), queue_prompt_node.ypos() + 35)
    read.knob('tile_color').setValue(
        queue_prompt_node.knob('tile_color').value())
