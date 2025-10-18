import os

# ENVIRONMENT VARIABLES
COMFYUI_DIR = os.getenv('NUKE_COMFYUI_DIR', '<Put the ComfyUI path here>')
IP = os.getenv('NUKE_COMFYUI_IP', '127.0.0.1')
PORT = int(os.getenv('NUKE_COMFYUI_PORT', '8188'))
COMFYUI2NUKE = os.path.dirname(__file__)
IMAGE_OUTPUT_WITHIN_PROJECT = os.getenv('IMAGE_OUTPUT_WITHIN_PROJECT', False)
COMFYUI_LOCAL = os.getenv('COMFYUI_LOCAL', True)

# SETTINGS
UPDATE_MENU_AT_START = False
USE_EXR_TO_LOAD_IMAGES = False
DISPLAY_META_IN_READ_NODE = True
TEMPORAL_DIR = os.path.join(os.path.expanduser("~"), '.nuke', 'comfyui_temp')
