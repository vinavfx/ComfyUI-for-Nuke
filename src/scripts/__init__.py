import json
import re

from . import export_workflow as export_workflow
from . import force_output_connection as force_output_connection
from . import knob2input as knob2input
from . import reload_node as reload_node
from . import unlink_dependencies as unlink_dependencies
from ...nuke_util.nuke_util import selected_node
from ...nuke_util.pyside import (
    QApplication,  # type: ignore
    QDialog,  # type: ignore
    QPushButton,  # type: ignore
    QTextEdit,  # type: ignore
    QVBoxLayout,  # type: ignore
)
from ..nodes import get_node_data

__all__ = [
    "export_workflow",
    "force_output_connection",
    "knob2input",
    "reload_node",
    "show_data",
    "unlink_dependencies",
]


def show_data():
    node = selected_node()
    if not node:
        return

    raw_json = json.dumps(get_node_data(node), indent=4)

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

    formatted_html = (
        "<span style='white-space: pre; font-family: monospace;'>{}</span>"
    ).format("\n".join(lines))

    dialog = QDialog(QApplication.activeWindow())
    dialog.setWindowTitle("ComfyUI Node Data")

    layout = QVBoxLayout(dialog)
    data_view = QTextEdit(dialog)
    data_view.setReadOnly(True)
    data_view.setHtml(formatted_html)
    layout.addWidget(data_view)

    close_button = QPushButton("Close", dialog)
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)

    font_metrics = data_view.fontMetrics()
    content_width = max(
        (font_metrics.boundingRect(line).width() for line in raw_json.splitlines()),
        default=0,
    )
    content_height = font_metrics.lineSpacing() * len(raw_json.splitlines())
    screen_size = QApplication.primaryScreen().availableGeometry().size()
    dialog_width = min(max(content_width + 110, 320), int(screen_size.width() * 0.8))
    dialog_height = min(
        max(content_height + 100, 180),
        int(screen_size.height() * 0.8),
    )
    dialog.resize(dialog_width, dialog_height)

    execute_dialog = getattr(dialog, "exec", None) or getattr(dialog, "exec_")
    execute_dialog()
