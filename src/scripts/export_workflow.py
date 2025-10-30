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
from ..common import update_images_and_mask_inputs, get_settings


def export_workflow():
    node = selected_node()
    if not node:
        return

    if node.knob('comfyui_gizmo'):
        node.begin()
        node = nuke.toNode('Run')

    elif not node.knob('comfyui_submit'):
        nuke.message("Select the 'Run' node")
        return

    settings = get_settings()
    update_images_and_mask_inputs(settings)
    data, _ = extract_data(node, settings)

    if not data:
        return

    workflow = nuke.getFilename(
        'Export Workflow',
        "*.json",
        os.path.join(os.path.expanduser('~'), 'Desktop/workflow.json'),
        type='save'
    )

    if not workflow:
        return

    workflow = workflow if 'json' in workflow else workflow + '.json'
    jwrite(workflow, data)

    nuke.message('Workflow Saved: ' + workflow)
