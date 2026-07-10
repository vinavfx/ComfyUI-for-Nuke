# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import re
import json
import queue
import threading
import nuke  # type: ignore
from .. import settings
from ..nuke_util.panels import panel_widget
from ..nuke_util import panels
from ..nuke_util.pyside import (QVBoxLayout, QTextEdit, QWidget, QTimer,
                                QIcon, QHBoxLayout, QPushButton, QCheckBox, Qt,
                                QComboBox, QFont, QTextCursor, QTextCharFormat,
                                QColor)
from .connection import format_URLs

import urllib.request as urllib2

panels.init('comfyui.console.console_panel', 'ComfyUI Console')


def show_console():
    widget = nuke.panels['comfyui_console']()
    widget.show()


class LogPoller:
    def __init__(self, url='127.0.0.1:8188'):
        self.url = format_URLs(url)[0]
        self._running = False
        self._thread = None
        self._last_timestamp = None
        self._queue = queue.Queue()
        self.on_message = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_messages(self):
        messages = []
        while True:
            try:
                messages.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def _poll_loop(self):
        while self._running:
            try:
                self._fetch_logs()
            except Exception:
                pass
            import time
            time.sleep(1)

    def _fetch_logs(self):
        url = '{}/internal/logs/raw'.format(self.url)
        req = urllib2.Request(url)
        response = urllib2.urlopen(req, timeout=5)
        data = json.loads(response.read().decode())

        entries = data.get('entries', [])
        for entry in entries:
            ts = entry.get('t', '')
            msg = entry.get('m', '')

            if self._last_timestamp and ts <= self._last_timestamp:
                continue

            self._last_timestamp = ts
            self._queue.put(msg)


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
        self.urls_box = QComboBox()
        self.urls_box.addItems(urls)
        self.urls_box.currentIndexChanged.connect(self._on_url_changed)

        self.log_button = QPushButton('Logs')
        self.log_button.setCheckable(True)
        self.log_button.clicked.connect(self._toggle_logs)

        monitor_button = QPushButton('Monitor')

        layout.addWidget(self.urls_box)
        layout.addStretch()
        layout.addWidget(self.log_button)
        layout.addWidget(monitor_button)

    def _on_url_changed(self, index):
        url = self.urls_box.currentText()
        output = self.parent.output_widget
        if url == '-':
            output.stop_log()
            output.clear()
        else:
            output.stop_log()
            output.start_log(url)

    def _toggle_logs(self):
        output = self.parent.output_widget
        if self.log_button.isChecked():
            url = self.urls_box.currentText()
            if url == '-':
                self.log_button.setChecked(False)
                return
            self.log_button.setText('Stop Logs')
            output.start_log(url)
        else:
            self.log_button.setText('Logs')
            output.stop_log()


class output_widget(QTextEdit):
    MAX_LINES = 1000
    ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')
    ANSI_COLORS = {
        '30': (0, 0, 0),       '31': (205, 50, 50),
        '32': (0, 200, 50),    '33': (200, 200, 50),
        '34': (50, 100, 205),  '35': (205, 50, 205),
        '36': (50, 200, 200),  '37': (220, 220, 220),
    }
    DEFAULT_COLOR = (200, 200, 200)

    def __init__(self, parent):
        QTextEdit.__init__(self, parent)
        self.parent = parent
        self.setReadOnly(True)
        self._poller = None

        font = QFont('Courier')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(font.pixelSize()+ 15)
        self.setFont(font)

        self.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #c8c8c8; }"
        )

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._flush_to_ui)

    def start_log(self, url=None):
        if self._poller and self._poller._running:
            return

        if not url:
            url = settings.URL
        self._poller = LogPoller(url)
        self._poller.start()
        self._poll_timer.start()

    def stop_log(self):
        if self._poller:
            self._poller.stop()
            self._poller = None
        self._poll_timer.stop()

    def _flush_to_ui(self):
        if not self._poller:
            return

        messages = self._poller.get_messages()
        if not messages:
            return

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        for msg in messages:
            self._insert_ansi_text(cursor, msg)
            if not msg.endswith('\n'):
                cursor.insertText('\n')

        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

        lines = self.document().blockCount()
        if lines > self.MAX_LINES:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                                lines - self.MAX_LINES)
            cursor.removeSelectedText()

    def _insert_ansi_text(self, cursor, text):
        parts = self.ANSI_RE.split(text)
        color = self.DEFAULT_COLOR

        for i, part in enumerate(parts):
            if i % 2 == 0:
                if part:
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor(*color))
                    cursor.insertText(part, fmt)
            else:
                codes = part.split(';')
                for code in codes:
                    if code in self.ANSI_COLORS:
                        color = self.ANSI_COLORS[code]
                    elif code == '0':
                        color = self.DEFAULT_COLOR

    def showEvent(self, event):
        super(output_widget, self).showEvent(event)

    def hideEvent(self, event):
        super(output_widget, self).hideEvent(event)
        self.stop_log()

    def keyPressEvent(self, event):
        ctrl = event.modifiers() == Qt.ControlModifier
        key = event.key()

        if ctrl and key == Qt.Key_Return:
            self.parent.execute_script()
        elif ctrl and key == Qt.Key_Backspace:
            self.clear()
        elif key == Qt.Key_Escape:
            self.parent.exit_node()

        QTextEdit.keyPressEvent(self, event)
