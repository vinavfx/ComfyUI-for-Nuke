import json
import weakref

import nuke  # type: ignore

from ...nuke_util.pyside import (  # type: ignore
    QTreeWidget,  # type: ignore
    QTreeWidgetItem,  # type: ignore
    QVBoxLayout,  # type: ignore
    QWidget,  # type: ignore
)
from ...src.execute_runs import sequential_submit

ORDER_KNOB = "gizmo_order"
SELECTION_KNOB = "selected_gizmo"
WIDGETS = []


def get_gizmos(node):
    gizmos = [child for child in node.nodes() if child.knob("comfyui_gizmo")]
    return sorted(gizmos, key=lambda child: (child.ypos(), child.xpos(), child.name()))


def read_order(node):
    knob = node.knob(ORDER_KNOB)
    if not knob:
        return []

    try:
        value = json.loads(knob.value() or "[]")
    except (TypeError, ValueError):
        return []

    if not isinstance(value, list):
        return []
    return [name for name in value if isinstance(name, str)]


def ordered_gizmos(node):
    gizmos = get_gizmos(node)
    gizmos_by_name = {gizmo.name(): gizmo for gizmo in gizmos}
    names = [name for name in read_order(node) if name in gizmos_by_name]
    names.extend(gizmo.name() for gizmo in gizmos if gizmo.name() not in names)
    return [gizmos_by_name[name] for name in names]


def save_order(node, names):
    knob = node.knob(ORDER_KNOB)
    if knob:
        knob.setValue(json.dumps(names))


def refresh_widgets(node):
    active_widget_refs = []
    node_name = node.fullName()
    for widget_ref in WIDGETS:
        widget = widget_ref()
        if widget is None:
            continue
        active_widget_refs.append(widget_ref)
        if widget.node_name == node_name:
            widget.reload()
    WIDGETS[:] = active_widget_refs


def update_content(node):
    gizmos = ordered_gizmos(node)
    save_order(node, [gizmo.name() for gizmo in gizmos])
    refresh_widgets(node)


def move_selected(node, offset):
    selection_knob = node.knob(SELECTION_KNOB)
    selected_name = selection_knob.value() if selection_knob else ""
    names = [gizmo.name() for gizmo in ordered_gizmos(node)]
    if selected_name not in names:
        return

    index = names.index(selected_name)
    target_index = index + offset
    if target_index < 0 or target_index >= len(names):
        return

    names[index], names[target_index] = names[target_index], names[index]
    save_order(node, names)
    refresh_widgets(node)


def run_gizmos(node):
    gizmos = get_gizmos(node)
    if not gizmos:
        nuke.message("MetaGizmo contains no ComfyUI gizmos.")
        return

    saved_names = read_order(node)
    current_names = [gizmo.name() for gizmo in gizmos]
    if len(saved_names) != len(current_names) or set(saved_names) != set(current_names):
        nuke.message(
            "MetaGizmo content has changed. Click Update Content before running."
        )
        return

    gizmos_by_name = {gizmo.name(): gizmo for gizmo in gizmos}
    gizmos = [gizmos_by_name[name] for name in saved_names]
    invalid_names = [
        gizmo.name()
        for gizmo in gizmos
        if nuke.toNode(gizmo.fullName() + ".Run") is None
    ]
    if invalid_names:
        nuke.message(
            "These ComfyUI gizmos do not contain a Run node:\n"
            + "\n".join(invalid_names)
        )
        return

    sequential_submit(gizmos)


class MetaGizmoWidget(QWidget):
    def __init__(self, node):
        super().__init__()
        self.node_name = node.fullName()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["ComfyUI gizmos"])
        self.tree.itemSelectionChanged.connect(self.save_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

        WIDGETS.append(weakref.ref(self))
        self.reload()

    def reload(self):
        node = nuke.toNode(self.node_name)
        if not node:
            return

        selection_knob = node.knob(SELECTION_KNOB)
        selected_name = selection_knob.value() if selection_knob else ""

        self.tree.blockSignals(True)
        self.tree.clear()
        for gizmo in ordered_gizmos(node):
            item = QTreeWidgetItem([gizmo.name()])
            self.tree.addTopLevelItem(item)
            if gizmo.name() == selected_name:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def save_selection(self):
        node = nuke.toNode(self.node_name)
        if not node:
            return

        selection_knob = node.knob(SELECTION_KNOB)
        if not selection_knob:
            return

        item = self.tree.currentItem()
        selection_knob.setValue(item.text(0) if item else "")


class MetaGizmoKnob:
    def makeUI(self):
        self.widget = MetaGizmoWidget(nuke.thisNode())
        return self.widget

    def updateValue(self):
        if hasattr(self, "widget"):
            self.widget.reload()
