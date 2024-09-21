# ComfyUI for Nuke
API to be able to use ComfyUI nodes within nuke, only using the ComfyUI server

<div style="display: flex;">
  <img src="images/screenshot.png"/>
</div>

## Requirements
  * Nuke 12 or higher (Not tested on previous versions !)
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
`websocket-client` is a third-party library needed for the scripts to work correctly. [Here is a direct link to it's pypi installation](https://pypi.org/project/websocket-client/). There are two main ways to install this:

#### Option A: Direct Installation (System-Wide)
This method installs the `websocket-client` library directly to your operating system’s Python environment.

1. Open a terminal (or command prompt on Windows) and run:
   ```bash
   pip install websocket-client
   ```

2. Then Copy these lines into <b>menu.py</b>
    ```python
    # Include path where websocket-client was installed
    # Windows: 'C:/Users/<USER>/AppData/Local/Programs/Python/Python37/Lib/site-packages'
    nuke.pluginAddPath('/home/<USER>/.local/lib/python3.7/site-packages') # Linux

    import nuke_comfyui as comfyui
    comfyui.setup()
    ```

#### Option B: Custom Module Imports using `NUKE_PATH`
If you want to use the module without adding it directly to the operating system python installation, you can set up `NUKE_PATH` to include your custom scripts and modules with a script to load those paths at Nuke startup:

1. **Create a Custom Directory**: Create a directory for your custom scripts, e.g., `C:\my_nuke_scripts` or `~/my_nuke_scripts`.
2. **Set the `NUKE_PATH` Environment Variable**:
    ```sh
    # Linux/Mac:
    export NUKE_PATH="/absolute/path/to/my_nuke_scripts"

    # Windows
    set NUKE_PATH="C:\absolute\path\to\my_nuke_scripts"
    ```
3. **In the `my_nuke_scripts` directory**: Create, or update, the `init.py` file with the following content:
   ```python
   import os
   import sys

   # Get the directory of this script
   nuke_path_dir = os.path.dirname(__file__)

   # Define your custom paths relative to this directory
   custom_paths = [
      os.path.join(nuke_path_dir, "_lib"),
   ]

   # Add each path to sys.path if it exists
   for path in custom_paths:
      if os.path.exists(path) and path not in sys.path:
         sys.path.append(path)
         print(f"path added: {path}")
   ```

### 3. Clone ComfyUI to any directory
```sh
git clone https://github.com/comfyanonymous/ComfyUI
```

### 4. Install ComfyUI-HQ-Image-Save (required to work with EXR)
```sh
cd <ComfyUI Directory>/custom_nodes
git clone https://github.com/spacepxl/ComfyUI-HQ-Image-Save.git
cd ./ComfyUI-HQ-Image-Save
pip install -r requirements.txt
```

### 5. Some nodes need additional repositories to work (Optional)
```sh
cd <ComfyUI Directory>/custom_nodes

# Upscale
git clone https://github.com/ssitu/ComfyUI_UltimateSDUpscale

# AnimateDiff
git clone https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git

# IPAdapter
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus

# Advanced ControlNet
git clone https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet.git

# LivePortrait
git clone https://github.com/kijai/ComfyUI-LivePortraitKJ.git
```

### 6. Download some models
```sh
cd <ComfyUI Directory>/models/checkpoints
wget https://huggingface.co/autismanon/modeldump/resolve/main/dreamshaper_8.safetensors

# to download more models on these pages !
# https://civitai.com
# https://huggingface.co
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
COMFYUI_DIR = '<ComfyUI>'
IP = '127.0.0.1'
PORT = 8188
NUKE_USER = '<.../.nuke>' # Change only if your path is different !
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
