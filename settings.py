import os

# ENVIRONMENT VARIABLES
HOME = str(os.environ.get('HOME'))
URL =                               os.getenv('NUKE_COMFYUI_URL', '127.0.0.1:8188')
COMFYUI2NUKE =                      os.path.dirname(__file__)
COLLECT_DIRECTORY =                 os.getenv('COLLECT_DIRECTORY', 'inferences')
INPUT_DIRECTORY =                   os.getenv('INPUT_DIRECTORY', os.path.join(HOME, 'ComfyUI/input'))
OUTPUT_DIRECTORY =                  os.getenv('OUTPUT_DIRECTORY', os.path.join(HOME, 'ComfyUI/output'))

# SETTINGS
UPDATE_MENU_AT_START = False
USE_EXR_TO_LOAD_IMAGES = False
DISPLAY_META_IN_READ_NODE = True
