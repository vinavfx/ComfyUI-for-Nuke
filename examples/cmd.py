# /usr/local/Nuke12.0v8 -t ./cmd.py
import nuke

nuke.scriptOpen('./cmd.nk')
run = nuke.toNode('Run')
run.knob('run').execute()

read = comfyui.cmd.get_read(run)
file = read.knob('file').value()
print(file)
