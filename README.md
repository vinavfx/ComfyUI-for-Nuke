# Nuke - ComfyUI
API to be able to use ComfyUI nodes within nuke, only using the ComfyUI server

## Installation
1 - Copy to nuke folder
```sh
# Linux:
cd ~/.nuke
git clone --recursive https://github.com/vinavfx/nuke_comfyui.git

# Windows
# Download git: https://git-scm.com/download/win
cd "C:\Users\<username>\.nuke"
git clone --recursive https://github.com/vinavfx/nuke_comfyui.git

# Or manually copy the entire git downloaded folder and its 
# submodules to the nuke user folder
```

2 - Copy this lines to <b>menu.py</b>
```python
import nuke_comfyui as comfyui
comfyui.setup()
```

3 - Clone ComfyUI to any directory
```sh
git clone https://github.com/comfyanonymous/ComfyUI
```

## Setup
1 - Run ComfyUI Server
```sh
cd <ComfyUI Directory>
python main.py
```
<img src='images/run_server.png' width=100%>

2 - Modify general variables in [settings.py](./settings.py)

```python
COMFYUI_DIR = '<ComfyUI>'
IP = '127.0.0.1'
PORT = 8188
```

