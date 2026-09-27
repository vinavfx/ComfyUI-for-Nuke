import json

import nuke  # type: ignore

from ...nuke_util.pyside import (  # type: ignore
    QHBoxLayout,  # type: ignore
    QPushButton,  # type: ignore
    QTreeWidget,  # type: ignore
    QTreeWidgetItem,  # type: ignore
    QVBoxLayout,  # type: ignore
    QWidget,  # type: ignore
)
from ...src.execute_runs import sequential_submit

ORDER_KNOB = "gizmo_order"
TREE_KNOB = "gizmo_tree"


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
        self.node = node
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["ComfyUI gizmos"])

        update_button = QPushButton("Update Content")
        update_button.clicked.connect(self.update_content)

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(lambda: self.move_selected(-1))

        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(lambda: self.move_selected(1))

        run_button = QPushButton("Run Gizmos")
        run_button.clicked.connect(lambda: run_gizmos(self.node))

        order_layout = QHBoxLayout()
        order_layout.addWidget(move_down_button)
        order_layout.addWidget(move_up_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        layout.addWidget(update_button)
        layout.addLayout(order_layout)
        layout.addWidget(run_button)

        self.reload()

    def names(self):
        return [
            self.tree.topLevelItem(index).text(0)
            for index in range(self.tree.topLevelItemCount())
        ]

    def reload(self):
        current_name = ""
        current_item = self.tree.currentItem()
        if current_item:
            current_name = current_item.text(0)

        self.tree.clear()
        for gizmo in ordered_gizmos(self.node):
            item = QTreeWidgetItem([gizmo.name()])
            self.tree.addTopLevelItem(item)
            if gizmo.name() == current_name:
                self.tree.setCurrentItem(item)

    def update_content(self):
        gizmos = ordered_gizmos(self.node)
        save_order(self.node, [gizmo.name() for gizmo in gizmos])
        self.reload()

    def move_selected(self, offset):
        item = self.tree.currentItem()
        if not item:
            return

        index = self.tree.indexOfTopLevelItem(item)
        target_index = index + offset
        if target_index < 0 or target_index >= self.tree.topLevelItemCount():
            return

        item = self.tree.takeTopLevelItem(index)
        self.tree.insertTopLevelItem(target_index, item)
        self.tree.setCurrentItem(item)
        save_order(self.node, self.names())


class MetaGizmoKnob:
    def makeUI(self):
        self.widget = MetaGizmoWidget(nuke.thisNode())
        return self.widget

    def updateValue(self):
        if hasattr(self, "widget"):
            self.widget.reload()


def install(node=None):
    node = node or nuke.thisNode()
    if node.knob(TREE_KNOB):
        return

    command = (
        "__import__('nukepath.comfyui2nuke.nodes.ComfyUI.MetaGizmo', "
        "fromlist=['MetaGizmoKnob']).MetaGizmoKnob()"
    )
    node.addKnob(nuke.PyCustom_Knob(TREE_KNOB, "", command))
