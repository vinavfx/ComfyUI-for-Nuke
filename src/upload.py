# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
from .common import get_comfyui_dir
import nuke  # type: ignore
import shutil


def upload_media():
    input_dir = os.path.join(get_comfyui_dir(), 'input')
    filepath = nuke.getFilename(
        'Upload Media', "*.jpg *.exr *.png *.mp3 *.wav")

    if not filepath:
        return

    this = nuke.thisNode()

    list_knob = this.knob('audio_')
    if not list_knob:
        list_knob = this.knob('image_')

    if not list_knob:
        return

    shutil.copy(filepath, input_dir)

    filename = os.path.basename(filepath)
    updated_options = list_knob.values()

    if not filename in updated_options:
        updated_options.append(filename)

    list_knob.setValues(updated_options)
    list_knob.setValue(filename)
