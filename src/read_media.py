# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import random
import nuke  # type: ignore

from ..nuke_util.nuke_util import get_input
from ..nuke_util.media_util import get_padding
from ..env import COMFYUI_DIR, NUKE_USER
from ..nuke_util.media_util import get_name_no_padding
from .nodes import get_connected_comfyui_nodes


def exr_filepath_fixed(queue_prompt_node):
    nodes = get_connected_comfyui_nodes(queue_prompt_node)
    for n, _ in nodes:
        filepath_knob = n.knob('filepath_')
        if not filepath_knob:
            continue

        filepath = filepath_knob.value()
        padding = get_padding(filepath)
        if not padding:
            continue

        filepath = filepath.replace(padding, '%04d')
        filepath_knob.setText(filepath)


def is_exr_linear(queue_prompt_node):
    output_node = get_input(queue_prompt_node, 0)

    if not output_node:
        return True

    sRGB_to_linear_knob = output_node.knob('sRGB_to_linear_')
    if not sRGB_to_linear_knob:
        return True

    return sRGB_to_linear_knob.value()


def update_filename_prefix(queue_prompt_node):
    output_node = get_input(queue_prompt_node, 0)
    if not output_node:
        return

    filename_prefix_knob = output_node.knob('filename_prefix_')
    if not filename_prefix_knob:
        return

    prefix = filename_prefix_knob.value()
    old_rand = prefix.split('/')[0]

    if old_rand.isdigit():
        prefix = prefix.replace(old_rand + '/', '')

    rand = random.randint(10000000000, 99999999990)
    new_prefix = os.path.join(str(rand), prefix)
    filename_prefix_knob.setValue(new_prefix)


def set_correct_colorspace(read):
    ocio = nuke.Root().knob('colorManagement').value()
    filename = read.knob('file').value()
    ext = filename.split('.')[-1]

    if ext == 'exr':
        read.knob('raw').setValue(True)
    else:
        read.knob('raw').setValue(False)
        read.knob('colorspace').setValue(
            'sRGB' if ocio == 'Nuke' else 'Output - sRGB')


def get_gizmo_group(queue_prompt_node):
    gizmo = queue_prompt_node

    while gizmo:
        gizmo = gizmo.parent()
        if not hasattr(gizmo, 'knob'):
            return

        if gizmo.knob('comfyui_gizmo'):
            return gizmo


def get_filename(queue_prompt_node):
    output_node = get_input(queue_prompt_node, 0)
    if not output_node:
        return

    filename_prefix_knob = output_node.knob('filename_prefix_')
    filepath_knob = output_node.knob('filepath_')

    if filename_prefix_knob:
        filename = filename_prefix_knob.value()
        filename_prefix = os.path.basename(filename)

        sequence_output = os.path.join(
            COMFYUI_DIR, 'output', os.path.dirname(filename))

    elif filepath_knob:
        filename = filepath_knob.value()
        filename_prefix = get_name_no_padding(filename)
        sequence_output = os.path.dirname(filename)

    else:
        return

    filenames = nuke.getFileNameList(sequence_output)
    if not filenames:
        return

    filename = next((fn for fn in filenames if filename_prefix in fn), None)

    if not filename:
        return

    return os.path.join(sequence_output, filename)


def create_read(queue_prompt_node, filename):
    if not filename:
        return

    main_node = get_gizmo_group(queue_prompt_node)
    if not main_node:
        main_node = queue_prompt_node

    main_node.parent().begin()

    name = '{}Read'.format(main_node.name())
    ext = filename.split('.')[-1].split(' ')[0].lower()

    if ext in ['jpg', 'exr', 'tiff', 'png']:
        read = nuke.toNode(name)
        if not read:
            read = nuke.createNode('Read', inpanel=False)

        read.knob('file').fromUserText(filename)
        set_correct_colorspace(read)

    elif ext in ['flac', 'mp3', 'wav']:
        read = nuke.toNode(name)
        if not read:
            read = nuke.nodePaste(os.path.join(
                NUKE_USER, 'nuke_comfyui', 'nodes', 'ComfyUI', 'AudioPlay.nk'))

        read.knob('audio').setValue(filename)
    else:
        return

    read.setName(name)
    read.setXYpos(main_node.xpos(), main_node.ypos() + 35)
    read.knob('tile_color').setValue(
        main_node.knob('tile_color').value())


def save_image_backup():
    queue_prompt_node = nuke.thisNode()

    main_node = get_gizmo_group(queue_prompt_node)
    if not main_node:
        main_node = queue_prompt_node

    main_node.parent().begin()

    read = nuke.toNode(main_node.name() + 'Read')
    if not read:
        return

    filename = '{} {}-{}'.format(read.knob('file').value(),
                                 read.knob('first').value(), read.knob('last').value())

    basename = get_name_no_padding(filename).replace(' ', '_')
    rand = os.path.basename(os.path.dirname(filename)).strip()
    name = '{}Backup_{}_{}'.format(main_node.name(), rand, basename)

    if not nuke.toNode(name):
        new_read = nuke.createNode('Read', inpanel=False)
        new_read.setName(name)
        new_read.knob('file').fromUserText(filename)
        set_correct_colorspace(new_read)

    xpos = read.xpos() + 50

    for n in nuke.allNodes():
        if not main_node.name() + 'Backup_' in n.name():
            continue

        xpos += 100
        n.setXYpos(xpos, read.ypos())
