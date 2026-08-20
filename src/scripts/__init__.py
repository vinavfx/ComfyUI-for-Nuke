from . import (
    knob2input,
    force_output_connection,
    export_workflow,
    reload_node,
)


import nuke  # type: ignore
from ..nodes import get_node_data
from ...nuke_util.nuke_util import selected_node
import json
import re


def show_data():
    node = selected_node()
    if not node:
        return

    raw_json = json.dumps(get_node_data(node), indent=10)

    lines = []
    for line in raw_json.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)

            key = f"<font color=#569CD6>{key}</font>"

            clean_val = val.strip().rstrip(",")
            comma = "," if val.strip().endswith(",") else ""

            if clean_val.startswith('"'):
                val = f"<font color=#98C379>{clean_val}</font>"
            elif clean_val in ["true", "false"]:
                val = f"<font color=#D19A66>{clean_val}</font>"
            elif clean_val == "null":
                val = f"<font color=#D19A66>{clean_val}</font>"
            elif re.match(r"^-?\d+(?:\.\d+)?$", clean_val):
                val = f"<font color=#D19A66>{clean_val}</font>"

            lines.append(f"{key}:{val}{comma}")
        else:
            lines.append(f"<font color=#ABB2BF>{line}</font>")

    formatted_msg = "<span style='white-space: pre;'>{}</span>".format("\n".join(lines))
    nuke.message(formatted_msg)
