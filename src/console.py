# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
from ..nuke_util.panels import panel_widget
from ..nuke_util import panels
from ..nuke_util.pyside import (QVBoxLayout, QTextEdit, QWidget, QTimer,
                                QIcon, QHBoxLayout, QPushButton, QCheckBox, Qt,
                                QComboBox)

panels.init('comfyui.console.console_panel', 'ComfyUI Console')


def show_console():
    widget = nuke.panels['comfyui_console']()
    widget.show()


class console_panel(panel_widget):
    def __init__(self, parent=None):
        super(console_panel, self).__init__(parent)
        self.margin = 2

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.output_widget = output_widget(self)
        self.toolbar = toolbar_widget(self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.output_widget)


class toolbar_widget(QWidget):
    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.parent = parent
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.setLayout(layout)

        urls = ["-", "127.0.0.1", "192.168.1.1"]
        urls_box = QComboBox()
        urls_box.addItems(urls)

        log_button = QPushButton('Logs')
        monitor_button = QPushButton('Monitor')

        layout.addWidget(urls_box)
        layout.addStretch()
        layout.addWidget(log_button)
        layout.addWidget(monitor_button)


class output_widget(QTextEdit):
    MAX_LINES = 1000

    def __init__(self, parent):
        QTextEdit.__init__(self, parent)
        self.parent = parent
        self.setReadOnly(True)
        self.last_pos = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.flush)

    def flush(self):
        nuke_console = get_nuke_console()
        if nuke_console:
            lines = nuke_console.toPlainText().split('\n')
            self.setPlainText('\n'.join(lines[-self.MAX_LINES:]))
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def update_output(self):
        nuke_console = get_nuke_console()
        if not nuke_console:
            return

        text = nuke_console.toPlainText()
        if len(text) > self.last_pos:
            self.last_pos = len(text)
            if not self.timer.isActive():
                self.timer.start()

    def clear_all(self):
        nuke_console = get_nuke_console()
        if not nuke_console:
            return

        self.clear()
        nuke_console.clear()
        self.last_pos = 0

    def add_output(self, output):
        nuke_console = get_nuke_console()
        if not nuke_console:
            return

        nuke_console.append(output)

    def keyPressEvent(self, event):
        ctrl = event.modifiers() == Qt.ControlModifier
        key = event.key()

        if ctrl and key == Qt.Key_Return:
            self.parent.execute_script()
        elif ctrl and key == Qt.Key_Backspace:
            self.parent.clean_output_console()
        elif key == Qt.Key_Escape:
            self.parent.exit_node()

        QTextEdit.keyPressEvent(self, event)
