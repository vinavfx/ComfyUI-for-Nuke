# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import os
from ..nodes import extract_data
from ...nuke_util.nuke_util import selected_node
from ...python_util.util import jwrite


def export_workflow():
    node = selected_node()
    if not node:
        return

    if not node.knob('comfyui_submit'):
        nuke.message("Select the 'Run' node")
        return

    workflow = nuke.getFilename(
        'Export Workflow', "*.json", os.path.join(os.path.expanduser('~'), 'Desktop/workflow'))

    if not workflow:
        return

    workflow = workflow if 'json' in workflow else workflow + '.json'
    data, _ = extract_data(node)
    jwrite(workflow, data)
