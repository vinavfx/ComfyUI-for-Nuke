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
from ..settings import COMFYUI_DIR, NUKE_USER, DISPLAY_META_IN_READ_NODE
from ..nuke_util.media_util import get_name_no_padding
from .nodes import get_connected_comfyui_nodes


def exr_filepath_fixed(run_node):
    nodes = get_connected_comfyui_nodes(run_node)
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


def get_tonemap(run_node):
    save_node = get_input(run_node, 0)

    if not save_node:
        return 'sRGB'

    tonemap_knob = save_node.knob('tonemap_')
    if not tonemap_knob:
        return 'sRGB'

    return tonemap_knob.value()


def update_filename_prefix(run_node):
    output_node = get_input(run_node, 0)
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
    new_prefix = '{}/{}'.format(rand, prefix)
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


def get_gizmo_group(run_node):
    gizmo = run_node

    while gizmo:
        gizmo = gizmo.parent()
        if not hasattr(gizmo, 'knob'):
            return

        if gizmo.knob('comfyui_gizmo'):
            return gizmo


def get_filename(run_node):
    output_node = get_input(run_node, 0)
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


def extract_meta(data):
    noise_seed = seed = steps = denoise = guidance = causvid = strength = -1
    scheduler = sampler_name = lora = lora2 = lora3 = cnet = ''

    for name, node in data.items():
        class_type = node['class_type']
        inputs = node['inputs']

        if noise_seed == -1:
            noise_seed = inputs.get('noise_seed', -1)

        if seed == -1:
            seed = inputs.get('seed', -1)

        if not sampler_name:
            sampler_name = inputs.get('sampler_name', '')

        if steps == -1:
            steps = inputs.get('steps', -1)

        if denoise == -1:
            denoise = inputs.get('denoise', -1)

        if not scheduler:
            scheduler = inputs.get('scheduler', '')

        if guidance == -1:
            guidance = inputs.get('guidance', -1)

        if causvid == -1:
            lora_name = inputs.get('lora_name', '')
            if 'CausVid' in lora_name:
                causvid = inputs.get('strength_model', 0)

        if class_type == 'WanVaceToVideo':
            strength = inputs.get('strength')

        if name in ('extra_lora1', 'extra_lora2', 'extra_lora3'):
            lora_name = inputs.get('lora_name', '').split('/')[-1].rsplit('.', 1)[0]
            lora_strength = inputs.get('strength_model', 0)
            formatted = '{}:{}'.format(lora_name, lora_strength)

            if name == 'extra_lora1':
                lora = formatted
            elif name == 'extra_lora2':
                lora2 = formatted
            elif name == 'extra_lora3':
                lora3 = formatted

        if class_type == 'ControlNetApplyAdvanced':
            cnet_strength = inputs.get('strength', 0)
            cnet_end = inputs.get('end_percent', 0)
            cnet = '{} : {}'.format(cnet_strength, cnet_end)

    meta = []

    if not seed == -1:
        meta.append(('seed', seed))

    if not noise_seed == -1:
        meta.append(('noise_seed', noise_seed))

    if not steps == -1:
        meta.append(('steps', steps))

    if sampler_name:
        meta.append(('sampler_name', sampler_name))

    if scheduler:
        meta.append(('scheduler', scheduler))

    if not denoise == -1:
        meta.append(('denoise', denoise))

    if not guidance == -1:
        meta.append(('guidance', guidance))

    if not strength == -1:
        meta.append(('strength', strength))

    if not causvid == -1:
        meta.append(('causvid', causvid))

    if cnet:
        meta.append(('CNet', cnet))

    if lora:
        meta.append(('lora', lora))

    if lora2:
        meta.append(('lora2', lora2))

    if lora3:
        meta.append(('lora3', lora3))

    return meta


def glb2obj(filename):
    import trimesh # type: ignore

    mesh = trimesh.load(filename)
    obj = filename[:-3] + 'obj'
    mesh.export(obj)

    read = nuke.createNode('ReadGeo', inpanel=False)
    read.knob('file').setValue(obj)
    read.setInput(0, None)

    return read


def get_frame_range(data):
    #  Of all the read nodes, it gets the longest range.
    ranges = [n.get('frame_range')
              for n in data.values() if n.get('frame_range')]
    if not ranges:
        return [1, 1]
    return max(ranges, key=lambda r: r[1] - r[0])


def create_read(run_node, filename, data={}):
    if not filename:
        return

    meta = []
    if data:
        meta = extract_meta(data)

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()

    fullname = '{}Read'.format(main_node.fullName())
    name = '{}Read'.format(main_node.name())
    ext = filename.split('.')[-1].split(' ')[0].lower()

    if ext in ['jpg', 'exr', 'tiff', 'png']:
        read = nuke.toNode(fullname)
        if not read:
            read = nuke.createNode('Read', inpanel=False)

        read.knob('file').fromUserText(filename)
        set_correct_colorspace(read)

    elif ext in ['flac', 'mp3', 'wav']:
        read = nuke.toNode(name)
        if not read:
            read = nuke.nodePaste(os.path.join(
                NUKE_USER, 'comfyui2nuke', 'nodes', 'ComfyUI', 'AudioPlay.nk'))

        read.knob('audio').setValue(filename)

    elif ext in ['glb']:
        read = glb2obj(filename)

    else:
        return

    read.setName(name)
    read.setXYpos(main_node.xpos(), main_node.ypos() + 35)
    read.knob('frame_mode').setValue('start at')
    read.knob('frame').setValue(str(get_frame_range(data)[0]))
    read.knob('tile_color').setValue(
        main_node.knob('tile_color').value())

    if meta and DISPLAY_META_IN_READ_NODE:
        label = '<center>'
        for key, value in meta:
            label += '<font color="green" size=1>{}:</font><font color="white" size=1> {}</>\n'.format(
                key, value)

        read.knob('label').setValue(label)

    return read


def save_image_backup(run_node=None):
    if not run_node:
        run_node = nuke.thisNode()

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

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
        new_read.knob('label').setValue(read.knob('label').value())
        new_read.knob('frame_mode').setValue(read.knob('frame_mode').value())
        new_read.knob('frame').setValue(read.knob('frame').value())
        set_correct_colorspace(new_read)

    xpos = read.xpos() + 50

    for n in nuke.allNodes('Read'):
        if not n.name().split('Backup')[0] == main_node.name():
            continue

        xpos += 100
        n.setXYpos(xpos, read.ypos())
