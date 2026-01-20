import os

# ENVIRONMENT VARIABLES
COMFYUI_DIR =                       os.getenv('NUKE_COMFYUI_DIR', '')
URL =                               os.getenv('NUKE_COMFYUI_URL', '127.0.0.1:8188')
COMFYUI2NUKE =                      os.path.dirname(__file__)
COMFYUI_LOCAL =                     bool(int(os.getenv('COMFYUI_LOCAL', '1')))
OUTPUT_DIRECTORY =                  os.getenv('OUTPUT_DIRECTORY', 'inferences')

# SETTINGS
UPDATE_MENU_AT_START = False
USE_EXR_TO_LOAD_IMAGES = False
DISPLAY_META_IN_READ_NODE = True
TEMPORAL_DIR = os.path.join(os.path.expanduser("~"), '.nuke', 'comfyui_temp')
