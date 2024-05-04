# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
from ..nuke_util.media_util import get_extension
from .common import get_comfyui_dir
import nuke  # type: ignore


def get_models(dirname, custom_nodes=False):
    if custom_nodes:
        models_dir = '{}/custom_nodes/{}'.format(get_comfyui_dir(), dirname)
    else:
        models_dir = '{}/models/{}'.format(get_comfyui_dir(), dirname)

    models = []

    for root, _, files in os.walk(models_dir):
        for f in files:
            if not get_extension(f) in ['ckpt', 'pth', 'safetensors']:
                continue

            relative_path = os.path.relpath(root, models_dir)
            if '.' == relative_path:
                relative_path = ''

            models.append(os.path.join(relative_path, f))

    if not models:
        nuke.message(
            'There is no model in the folder "{}" !'.format(models_dir))

    return models
