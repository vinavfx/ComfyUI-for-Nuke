# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import re
import json
import queue
import threading
import urllib.request as urllib_request

import nuke  # type: ignore
from ..nuke_util.panels import panel_widget
from ..nuke_util import panels
from ..nuke_util.pyside import (QVBoxLayout, QTextEdit, QWidget, QTimer,
                                QHBoxLayout, QPushButton, Qt,
                                QComboBox, QFont, QTextCursor, QTextCharFormat,
                                QColor)
from .. import settings
from .connection import format_URLs

panels.init('comfyui.console.console_panel', 'ComfyUI Console')


def show_console():
    widget = nuke.panels['comfyui_console']()
    widget.show()


class LogPoller:
    POLL_INTERVAL = 1

    def __init__(self, url='127.0.0.1:8188'):
        self.url = format_URLs(url)[0]
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_timestamp = None

    @property
    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.is_running:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=self.POLL_INTERVAL + 1)
        self.thread = None

    def get_messages(self):
        messages = []
        while True:
            try:
                messages.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def poll_loop(self):
        while not self.stop_event.is_set():
            try:
                self.fetch_logs()
            except Exception:
                pass
            self.stop_event.wait(self.POLL_INTERVAL)

    def fetch_logs(self):
        url = '{}/internal/logs/raw'.format(self.url)
        response = urllib_request.urlopen(url, timeout=5)
        data = json.loads(response.read().decode())

        for entry in data.get('entries', []):
            timestamp = entry.get('t', '')
            message = entry.get('m', '')

            if self.last_timestamp and timestamp <= self.last_timestamp:
                continue

            self.last_timestamp = timestamp
            self.queue.put(message)

    def get_latest_timestamp(self):
        try:
            url = '{}/internal/logs/raw'.format(self.url)
            response = urllib_request.urlopen(url, timeout=5)
            data = json.loads(response.read().decode())
            entries = data.get('entries', [])
            if entries:
                return entries[-1].get('t', '')
        except Exception:
            pass
        return None


class console_panel(panel_widget):
    def __init__(self, parent=None):
        super(console_panel, self).__init__(parent)
        self.margin = 2

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.output_widget = output_widget(self)
        self.toolbar = toolbar_widget(self.output_widget)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.output_widget)


class toolbar_widget(QWidget):
    def __init__(self, output_widget):
        QWidget.__init__(self, output_widget.parent)
        self.output_widget = output_widget

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.setLayout(layout)

        self.urls_box = QComboBox()
        self.urls_box.addItems(['-', '127.0.0.1', '192.168.1.1'])
        self.urls_box.currentIndexChanged.connect(self.on_url_changed)

        self.log_button = QPushButton('Logs')
        self.log_button.setCheckable(True)
        self.log_button.clicked.connect(self.toggle_logs)

        self.clean_button = QPushButton('Clean Output Console')
        self.clean_button.clicked.connect(self.clean_output)

        layout.addWidget(self.urls_box)
        layout.addStretch()
        layout.addWidget(self.log_button)
        layout.addWidget(self.clean_button)

    def on_url_changed(self, _):
        self.output_widget.stop_log()

        url = self.urls_box.currentText()
        if url == '-':
            self.log_button.setChecked(False)
            self.log_button.setText('Logs')
            self.output_widget.clear()
        else:
            self.output_widget.start_log(url)
            self.log_button.setChecked(True)
            self.log_button.setText('Stop Logs')

    def toggle_logs(self, checked):
        url = self.urls_box.currentText()

        if checked and url == '-':
            self.log_button.setChecked(False)
            return

        if checked:
            self.output_widget.start_log(url)
            self.log_button.setText('Stop Logs')
        else:
            self.output_widget.stop_log()
            self.log_button.setText('Logs')

    def clean_output(self):
        self.output_widget.clear()


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
        self.document().setMaximumBlockCount(self.MAX_LINES)
        self.poller = None

        font = QFont('DejaVu Sans Mono')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(font.pixelSize() + 14)
        self.setFont(font)

        self.setStyleSheet(
            'QTextEdit { background-color: #1e1e1e; color: #c8c8c8; }'
        )

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self.flush_to_ui)

    def start_log(self, url=None):
        if self.poller and self.poller.is_running:
            return

        self.poller = LogPoller(url or settings.URL)
        self.poller.start()
        self.poll_timer.start()

    def start_log_from(self, url, last_timestamp):
        if self.poller and self.poller.is_running:
            return

        self.poller = LogPoller(url or settings.URL)
        self.poller.last_timestamp = last_timestamp
        self.poller.start()
        self.poll_timer.start()

    def stop_log(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        self.poll_timer.stop()

    def flush_to_ui(self):
        if not self.poller:
            return

        messages = self.poller.get_messages()
        if not messages:
            return

        scrollbar = self.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 4

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        for msg in messages:
            self.insert_ansi_text(cursor, msg)
            if not msg.endswith('\n'):
                cursor.insertText('\n')

        self.setTextCursor(cursor)

        if was_at_bottom:
            QTimer.singleShot(0, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def insert_ansi_text(self, cursor, text):
        parts = self.ANSI_RE.split(text)
        color = self.DEFAULT_COLOR

        for i, part in enumerate(parts):
            if i % 2 == 0:
                if part:
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor(*color))
                    cursor.insertText(part, fmt)
                continue

            for code in part.split(';'):
                if code in self.ANSI_COLORS:
                    color = self.ANSI_COLORS[code]
                elif code == '0':
                    color = self.DEFAULT_COLOR

    def hideEvent(self, event):
        super(output_widget, self).hideEvent(event)
        self.stop_log()

    def showEvent(self, event):
        super(output_widget, self).showEvent(event)
        parent = self.parent
        if hasattr(parent, 'toolbar') and parent.toolbar.log_button.isChecked():
            url = parent.toolbar.urls_box.currentText()
            temp_poller = LogPoller(url)
            latest_ts = temp_poller.get_latest_timestamp()
            self.start_log_from(url, latest_ts)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Backspace:
            self.clear()
            if self.poller:
                latest_ts = self.poller.get_latest_timestamp()
                url = self.poller.url
                self.stop_log()
                self.start_log_from(url, latest_ts)
        QTextEdit.keyPressEvent(self, event)
