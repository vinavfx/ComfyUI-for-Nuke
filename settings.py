import os

# ENVIRONMENT VARIABLES
URL =                               os.getenv('NUKE_COMFYUI_URL', '127.0.0.1:8188')
COMFYUI2NUKE =                      os.path.dirname(__file__)
COLLECT_DIRECTORY =                 os.getenv('COLLECT_DIRECTORY', 'inferences')
INPUT_DIRECTORY =                   os.getenv('INPUT_DIRECTORY', None)
OUTPUT_DIRECTORY =                  os.getenv('OUTPUT_DIRECTORY', None)
ALLOW_ALL_IPS_SUBMIT =              bool(int(os.getenv('ALLOW_ALL_IPS_SUBMIT', '1')))

# SETTINGS
UPDATE_MENU_AT_START = False
USE_EXR_TO_LOAD_IMAGES = False
DISPLAY_META_IN_READ_NODE = True
