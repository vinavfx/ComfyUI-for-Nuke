# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import re
import json
import time
import queue
import threading
import urllib.request as urllib_request

import nuke  # type: ignore
from .. import settings
from ..nuke_util.panels import panel_widget
from ..nuke_util import panels
from ..nuke_util.pyside import (QVBoxLayout, QTextEdit, QWidget, QTimer,
                                QHBoxLayout, QPushButton, Qt,
                                QComboBox, QFont, QTextCursor, QTextCharFormat,
                                QColor)
from .connection import format_URLs

panels.init('comfyui.console.console_panel', 'ComfyUI Console')


def show_console():
    widget = nuke.panels['comfyui_console']()
    widget.show()


class LogPoller:
    '''
    Sondea el endpoint de logs de ComfyUI en un hilo aparte y entrega
    los mensajes nuevos a través de una queue thread-safe.
    '''
    POLL_INTERVAL = 1  # segundos

    def __init__(self, url='127.0.0.1:8188'):
        self.url = format_URLs(url)[0]
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = None
        self._last_timestamp = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.POLL_INTERVAL + 1)
        self._thread = None

    def get_messages(self):
        messages = []
        while True:
            try:
                messages.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._fetch_logs()
            except Exception:
                pass
            self._stop_event.wait(self.POLL_INTERVAL)

    def _fetch_logs(self):
        url = '{}/internal/logs/raw'.format(self.url)
        response = urllib_request.urlopen(url, timeout=5)
        data = json.loads(response.read().decode())

        for entry in data.get('entries', []):
            timestamp = entry.get('t', '')
            message = entry.get('m', '')

            if self._last_timestamp and timestamp <= self._last_timestamp:
                continue

            self._last_timestamp = timestamp
            self._queue.put(message)


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
    '''
    output_widget: instancia de output_widget que este toolbar controla.
    '''
    def __init__(self, output_widget):
        QWidget.__init__(self, output_widget.parent)
        self.output_widget = output_widget

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.setLayout(layout)

        self.urls_box = QComboBox()
        self.urls_box.addItems(['-', '127.0.0.1', '192.168.1.1'])
        self.urls_box.currentIndexChanged.connect(self._on_url_changed)

        self.log_button = QPushButton('Logs')
        self.log_button.setCheckable(True)
        self.log_button.clicked.connect(self._toggle_logs)

        layout.addWidget(self.urls_box)
        layout.addStretch()
        layout.addWidget(self.log_button)

    def _on_url_changed(self, _index):
        self.output_widget.stop_log()
        self.log_button.setChecked(False)
        self.log_button.setText('Logs')

        url = self.urls_box.currentText()
        if url == '-':
            self.output_widget.clear()

    def _toggle_logs(self, checked):
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
        self._poller = None

        font = QFont('DejaVu Sans Mono')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(font.pixelSize() + 14)
        self.setFont(font)

        self.setStyleSheet(
            'QTextEdit { background-color: #1e1e1e; color: #c8c8c8; }'
        )

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._flush_to_ui)

    def start_log(self, url=None):
        if self._poller and self._poller.is_running:
            return

        self._poller = LogPoller(url or settings.URL)
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

        scrollbar = self.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 4

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        for msg in messages:
            self._insert_ansi_text(cursor, msg)
            if not msg.endswith('\n'):
                cursor.insertText('\n')

        # Mueve el cursor real del widget al final para que
        # ensureCursorVisible funcione de forma confiable, incluso
        # cuando setMaximumBlockCount recorta bloques por arriba.
        self.setTextCursor(cursor)

        if was_at_bottom:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _insert_ansi_text(self, cursor, text):
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

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Backspace:
            self.clear()
        QTextEdit.keyPressEvent(self, event)
