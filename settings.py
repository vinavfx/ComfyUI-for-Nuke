import os
from .nuke_util.nuke_util import get_nuke_path

# ENVIRONMENT VARIABLES
COMFYUI_DIR = os.getenv('NUKE_COMFYUI_DIR', '<Put the ComfyUI path here>')
IP = os.getenv('NUKE_COMFYUI_IP', '127.0.0.1')
PORT = int(os.getenv('NUKE_COMFYUI_PORT', '8188'))
NUKE_USER = os.getenv('NUKE_COMFYUI_NUKE_USER', get_nuke_path())

# SETTINGS
UPDATE_MENU_AT_START = False
USE_EXR_TO_LOAD_IMAGES = False
