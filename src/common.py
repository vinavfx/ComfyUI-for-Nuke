# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
from ..settings import COMFYUI_DIR

image_inputs = ['image', 'frames', 'pixels']
mask_inputs = ['mask', 'attn_mask', 'mask_optional']


def get_available_name(prefix, directory):
    prefix += '_'
    taken_names = set(os.listdir(directory))

    for i in range(10000):
        potential_name = '{}{:04d}'.format(prefix, i)
        if potential_name not in taken_names:
            return potential_name

    return prefix


def get_comfyui_dir():
    if os.path.isdir(os.path.join(COMFYUI_DIR, 'comfy')):
        return COMFYUI_DIR

    nuke.message('Directory "{}" does not exist'.format(COMFYUI_DIR))

    return ''
