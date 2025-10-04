# ComfyUI for Nuke
API to be able to use ComfyUI nodes within nuke, only using the ComfyUI server

<div style="display: flex;">
  <img src="images/screenshot.png"/>
</div>

## Requirements
  * Nuke 11 or higher (Not tested on previous versions !)
  * `websocket-client` Python library
  * <a href="https://github.com/comfyanonymous/ComfyUI" target="_blank">ComfyUI</a>
  * ComfyUI-VideoHelperSuite (required to load images and sequences)
  * ComfyUI-HQ-Image-Save (if you want to work in exr)

## Installation
### 1. Copy to nuke folder
   ```sh
   # Linux:
   cd ~/.nuke
   git clone --recursive https://github.com/vinavfx/ComfyUI-for-Nuke comfyui2nuke

   # Windows
   # Download git: https://git-scm.com/download/win
   cd "C:\Users\<username>\.nuke"
   git clone --recursive https://github.com/vinavfx/ComfyUI-for-Nuke comfyui2nuke
   ```
Or manually copy the entire git downloaded folder and its submodules to the nuke user folder

### 2. Install `websocket-client` Python Library
`websocket-client` is a third-party library needed for the scripts to work correctly. [Here is a direct link to it's pypi installation](https://pypi.org/project/websocket-client/).

This method installs the `websocket-client` library directly to your Nuke's Python environment.
This example will be done with Nuke version 15.1v3, depending on your version change the number.

Open a terminal (or command prompt on Windows) and run:
   ```bash
    # Linux/Mac:
   /usr/local/Nuke15.1v3/python3 -m pip install websocket-client

    # Windows (As administrator)
    "C:\Program Files\Nuke15.1v3\python.exe" -m pip install websocket-client
   ```

### 3. Copy these lines into <b>menu.py</b>

You can then add or update your Nuke `menu.py` file to include the location of your site-packages installation,
It is not necessary to add the site-package if websocket was installed with the root or administrator user,
since in that case it would be within the Nuke installation !

```python
# Linux/Mac:
nuke.pluginAddPath('{}/.local/lib/python{}.{}/site-packages'.format(
    os.path.expanduser('~'), sys.version_info.major, sys.version_info.minor))

# Windows (Add only in Nuke older than 12.2)
nuke.pluginAddPath('C:/Python27/Lib/site-packages')
```

```python
import comfyui2nuke as comfyui
comfyui.setup()
```

## Setup
1 - Modify environment variables in [settings.py](./settings.py)

```python
COMFYUI_DIR = '<path_to_ComfyUI>' # Put the directory where ComfyUI is installed !
IP = '127.0.0.1'
PORT = 8188
```
Alternatively, you can set these environment variables instead of modifying [settings.py](./settings.py)
- `NUKE_COMFYUI_DIR` - Path where ComfyUI directory is mounted/mapped
- `NUKE_COMFYUI_IP` - IP address of the remote ComfyUI server
- `NUKE_COMFYUI_PORT` - Port number (default: 8188)

2 - Run ComfyUI Server

## Tips
1 - When connecting any image or roto from Nuke, take into consideration the <b>'FrameRange'</b>
of the output because that will be the batch size.

2 - To make ComfyUI work with pixel values greater than 1 and less than 0, change tonemap knob to <b>'linear'</b> in the <b>'SaveEXR'</b> node

3 - Latent images only work with formats with multiple of 8, add the '<b>PrepareImageForLatent</b>' node before passing the image
to latent, and in the same node there is a button to create a restore node, put it on the image after inference to restore.

4 - To load all ComfyUI nodes when Nuke starts, change the '<b>UPDATE_MENU_AT_START</b>' variable in the [settings.py](./settings.py) file

5 - To use Switch in ComfyUI nodes statically, use '<b>SwitchAny</b>' otherwise use the ComfyUI switches

6 - If you want to have the ComfyUI server on another machine, you must share the folder where ComfyUI is installed and put the path in [setting.py](./settings.py)
