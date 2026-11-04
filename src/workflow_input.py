import json
import os

from ..nuke_util.pyside import QApplication, QEvent, QKeySequence, QtCore
from .workflow_importer import import_workflow_data

workflow_input_filter = None


def workflow_from_text(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return None
    if not all(
        isinstance(node, dict) and "id" in node and "type" in node
        for node in data["nodes"]
    ):
        return None
    return data


def workflows_from_mime(mime):
    if mime.hasUrls():
        workflows = []
        for url in mime.urls():
            path = url.toLocalFile()
            if not path or os.path.splitext(path)[1].lower() != ".json":
                return []
            try:
                with open(path, encoding="utf-8-sig") as stream:
                    data = workflow_from_text(stream.read())
            except (OSError, UnicodeError):
                return []
            if data is None:
                return []
            workflows.append((data, os.path.splitext(os.path.basename(path))[0]))
        return workflows
    data = workflow_from_text(mime.text())
    return [(data, None)] if data is not None else []


def is_node_graph(widget):
    while widget is not None:
        if any(
            widget.inherits(name)
            for name in (
                "QLineEdit",
                "QTextEdit",
                "QPlainTextEdit",
                "QAbstractSpinBox",
                "QComboBox",
            )
        ):
            return False
        if "DAG" in widget.objectName():
            return True
        widget = widget.parent()
    return False


def import_workflows(workflows):
    for data, name in workflows:
        import_workflow_data(data, name)


class WorkflowInputFilter(QtCore.QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.drag_workflows = []

    def eventFilter(self, watched, event):
        event_type = event.type()
        supported = (
            QEvent.ShortcutOverride,
            QEvent.KeyPress,
            QEvent.DragEnter,
            QEvent.DragMove,
            QEvent.DragLeave,
            QEvent.Drop,
        )
        if event_type not in supported or not is_node_graph(watched):
            return False
        if event_type in (QEvent.ShortcutOverride, QEvent.KeyPress):
            if not event.matches(QKeySequence.Paste):
                return False
            clipboard = QApplication.clipboard()
            workflows = workflows_from_mime(clipboard.mimeData())
            if not workflows:
                return False
            event.accept()
            if event_type == QEvent.KeyPress:
                import_workflows(workflows)
            return True
        if event_type == QEvent.DragLeave:
            self.drag_workflows = []
            return False
        if event_type == QEvent.DragEnter:
            self.drag_workflows = workflows_from_mime(event.mimeData())
        if event_type == QEvent.Drop:
            workflows = workflows_from_mime(event.mimeData())
            self.drag_workflows = []
            if not workflows:
                return False
            event.acceptProposedAction()
            import_workflows(workflows)
            return True
        if self.drag_workflows:
            event.acceptProposedAction()
            return True
        return False


def install():
    global workflow_input_filter
    application = QApplication.instance()
    if application is None or workflow_input_filter is not None:
        return
    workflow_input_filter = WorkflowInputFilter(application)
    application.installEventFilter(workflow_input_filter)
