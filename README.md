# ComfyUI for Nuke
API to be able to use ComfyUI nodes within nuke, only using the ComfyUI server

<div style="display: flex;">
  <img src="images/screenshot.png"/>
</div>

##### SUPPORT THE MAINTENANCE OF THIS PROJECT:
[![](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/paypalme/ComfyUIforNuke)

## Requirements
  * Nuke 11 or higher (Not tested on previous versions !)
  * `websocket-client` Python library
  * <a href="https://github.com/comfyanonymous/ComfyUI" target="_blank">ComfyUI</a>
  * ComfyUI-HQ-Image-Save (required to load images and sequences and work with EXR)

## Installation
### 1. Copy to nuke folder
   ```sh
   # Linux:
   cd ~/.nuke
   git clone --recursive https://github.com/vinavfx/ComfyUI-for-Nuke nuke_comfyui

   # Windows
   # Download git: https://git-scm.com/download/win
   cd "C:\Users\<username>\.nuke"
   git clone --recursive https://github.com/vinavfx/ComfyUI-for-Nuke nuke_comfyui
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
import nuke_comfyui as comfyui
comfyui.setup()
```

### 4. Install ComfyUI-Manager
```sh
cd <ComfyUI Directory>/custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager.git
cd ./ComfyUI-Manager
pip install -r requirements.txt
```

### 5. Install ComfyUI-HQ-Image-Save (required to work with EXR)
```sh
cd <ComfyUI Directory>/custom_nodes
git clone https://github.com/spacepxl/ComfyUI-HQ-Image-Save.git
cd ./ComfyUI-HQ-Image-Save
pip install -r requirements.txt
```

## Setup
1 - Run ComfyUI Server
```sh
cd <ComfyUI Directory>
python main.py
```
<img src='images/run_server.png' width=100%>

2 - Modify environment variables in [env.py](./env.py)

```python
COMFYUI_DIR = '<path_to_ComfyUI>' # Put the directory where ComfyUI is installed !
IP = '127.0.0.1'
PORT = 8188
NUKE_USER = '<path_to_.nuke>' # Change only if your path is different !
```

## Tips
1 - When connecting any image or roto from Nuke, take into consideration the <b>'FrameRange'</b>
of the output because that will be the batch size.

2 - To make ComfyUI work with pixel values greater than 1 and less than 0, uncheck the <b>'sRGB_to_linear'</b> box in the <b>'SaveEXR'</b> node

3 - Latent images only work with formats with multiple of 8, add the '<b>PrepareImageForLatent</b>' node before passing the image
to latent, and in the same node there is a button to create a restore node, put it on the image after inference to restore.

4 - To load all ComfyUI nodes when Nuke starts, change the '<b>update_menu_at_start</b>' variable in the [__init__.py](./__init__.py) file

5 - To use Switch on ComfyUI nodes use '<b>SwitchAny</b>' as ComfyUI switch nodes don't work
because they have 'any *' inputs and outputs, which is not possible on nuke because it doesn't have multiple outputs.

6 - If you want to have the ComfyUI server on another machine, you must share the folder where ComfyUI is installed and put the path in [env.py](./env.py)

7 - Use the QueuePrompt '<b>Force Animation</b>' method only if you have some keyframes animated,
as this way is slower because it sends requests frame by frame and not in batches.
