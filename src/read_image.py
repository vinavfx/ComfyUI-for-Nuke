# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import shutil
import os
import nuke  # type: ignore

from .common import get_comfyui_dir
from ..nuke_util.nuke_util import get_project_name


def outside_read(queue_prompt_node, reload=False):
    queue_prompt_node.begin()
    inside_read = nuke.toNode('read')
    queue_prompt_node.end()

    name = '{}Read'.format(queue_prompt_node.name())
    outside_read = queue_prompt_node.knob('outside_read').value()

    queue_prompt_node.parent().begin()

    if not outside_read:
        nuke.delete(nuke.toNode(name))
        return

    read = nuke.toNode(name)
    if not read:
        read = nuke.createNode('Read', inpanel=False)

    read.setXYpos(queue_prompt_node.xpos(), queue_prompt_node.ypos() + 35)
    read.knob('tile_color').setValue(
        queue_prompt_node.knob('tile_color').value())
    read.knob('on_error').setValue('black')

    read.setName(name)

    for knobname in ['file', 'first', 'last', 'origlast', 'origfirst', 'colorspace', 'raw']:
        read.knob(knobname).setValue(inside_read.knob(knobname).value())

    if reload:
        read.knob('reload').execute()

    queue_prompt_node.parent().end()


def get_filename_prefix(queue_prompt_node):
    filename_prefix = '{}_{}'.format(
        get_project_name(), queue_prompt_node.fullName())
    return filename_prefix


def post_submit(queue_prompt_node):
    prefix = get_filename_prefix(queue_prompt_node)
    output_dir = '{}/output'.format(get_comfyui_dir())
    sequence_dir = '{}/{}'.format(output_dir, prefix)

    shutil.rmtree(sequence_dir, ignore_errors=True)
    os.mkdir(sequence_dir)

    frames = queue_prompt_node.input(0).lastFrame()
    last_frame = 0

    for i in range(frames):
        frame = '00000{}'.format(i + 1)[-5:]
        src = '{}/{}_{}_.png'.format(output_dir, prefix, frame)
        dst = '{}/{}_{}_.png'.format(sequence_dir, prefix, frame)

        if os.path.isfile(src):
            shutil.move(src, dst)
            last_frame = i + 1

    # en el 'for' superior ya se copian las imagenes por rango de frames, pero a veces
    # cuando hay 1 imagen comfyui comienza del padding 2 y no coincide con los frames
    for f in os.listdir(output_dir):
        if os.path.isdir(os.path.join(output_dir, f)):
            continue

        if prefix + '_' in f:
            shutil.move(os.path.join(output_dir, f),
                        os.path.join(sequence_dir, f))

    filename = '{}/{}_#####_.png'.format(sequence_dir, prefix)
    filename = filename.replace('\\', '/')

    queue_prompt_node.begin()
    read = nuke.toNode('read')
    output_node = nuke.toNode('Output')
    queue_prompt_node.end()

    ocio = nuke.Root().knob('colorManagement').value()

    output_node.setInput(0, read)
    read.knob('file').setValue(filename)
    read.knob('first').setValue(1)
    read.knob('last').setValue(last_frame)
    read.knob('origfirst').setValue(1)
    read.knob('origlast').setValue(last_frame)
    read.knob('colorspace').setValue(
        'sRGB' if ocio == 'Nuke' else 'Output - sRGB')
    read.knob('reload').execute()

    outside_read(queue_prompt_node, reload=True)
