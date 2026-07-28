# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
import shutil

from .common import get_settings


def upload_media():
    settings = get_settings()
    input_dir = settings["INPUT_DIRECTORY"]
    filepath = nuke.getFilename("Upload Media", "*.jpg *.exr *.png *.mp3 *.wav")

    if not filepath:
        return

    this = nuke.thisNode()

    list_knob = this.knob("audio_")
    if not list_knob:
        list_knob = this.knob("image_")

    if not list_knob:
        return

    shutil.copy(filepath, input_dir)

    filename = os.path.basename(filepath)
    updated_options = list_knob.values()

    if not filename in updated_options:
        updated_options.append(filename)

    list_knob.setValues(updated_options)
