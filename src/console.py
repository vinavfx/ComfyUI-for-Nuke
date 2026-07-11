# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
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
                                QColor, QIcon, QSize)
from .. import settings
from .connection import format_URLs
from .common import get_settings

panels.init('comfyui.console.console_panel', 'ComfyUI Console')

LOGS_ENDPOINT = 'Logs'
SYSTEM_STATS_ENDPOINT = 'System Stats'
LOGS_RAW_PATH = '/internal/logs/raw'
SYSTEM_STATS_PATH = '/system_stats'


def show_console():
    widget = nuke.panels['comfyui_console']()
    widget.show()


def fetch_json(url, timeout=5):
    response = urllib_request.urlopen(url, timeout=timeout)
    return json.loads(response.read().decode())


def ansi(code, text):
    return '\x1b[{}m{}\x1b[0m'.format(code, text)


def format_json_ansi(data, indent=0):
    pad = '  ' * indent
    pad_in = '  ' * (indent + 1)

    if isinstance(data, dict):
        if not data:
            return '{}'

        items = list(data.items())
        lines = ['{']
        for i, (key, value) in enumerate(items):
            comma = ',' if i < len(items) - 1 else ''
            key_str = ansi('36', '"{}"'.format(key))
            value_str = format_json_ansi(value, indent + 1)
            lines.append('{}{}: {}{}'.format(pad_in, key_str, value_str, comma))
        lines.append(pad + '}')
        return '\n'.join(lines)

    if isinstance(data, list):
        if not data:
            return '[]'

        lines = ['[']
        for i, value in enumerate(data):
            comma = ',' if i < len(data) - 1 else ''
            value_str = format_json_ansi(value, indent + 1)
            lines.append('{}{}{}'.format(pad_in, value_str, comma))
        lines.append(pad + ']')
        return '\n'.join(lines)

    if isinstance(data, bool):
        return ansi('35', 'true' if data else 'false')

    if data is None:
        return ansi('35', 'null')

    if isinstance(data, (int, float)):
        return ansi('33', data)

    if isinstance(data, str):
        return ansi('32', '"{}"'.format(data))

    return str(data)


class LogPoller:
    POLL_INTERVAL = 1

    def __init__(self, url='127.0.0.1:8188', error_callback=None):
        self.url = format_URLs(url)[0]
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_timestamp = None
        self.error_callback = error_callback
        self.last_error = None

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
                self.last_error = None
            except Exception as e:
                error_msg = str(e)
                if self.last_error != error_msg:
                    self.last_error = error_msg
                    if self.error_callback:
                        self.error_callback(error_msg)
            self.stop_event.wait(self.POLL_INTERVAL)

    def fetch_log_data(self):
        url = '{}{}'.format(self.url, LOGS_RAW_PATH)
        return fetch_json(url)

    def fetch_logs(self):
        data = self.fetch_log_data()

        for entry in data.get('entries', []):
            timestamp = entry.get('t', '')
            message = entry.get('m', '')

            if self.last_timestamp and timestamp <= self.last_timestamp:
                continue

            self.last_timestamp = timestamp
            self.queue.put(message)

    def get_latest_timestamp(self):
        try:
            entries = self.fetch_log_data().get('entries', [])
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
        self.urls_box.addItems(['-'] + format_URLs(get_settings()['URL'], protocol=False))
        self.urls_box.currentIndexChanged.connect(self.on_url_changed)

        self.endpoint_box = QComboBox()
        self.endpoint_box.addItems([LOGS_ENDPOINT, SYSTEM_STATS_ENDPOINT])
        self.endpoint_box.currentIndexChanged.connect(self.on_endpoint_changed)

        self.log_button = self.make_icon_button(
            'list.png', 'Start and Stop Logs', checkable=True)
        self.log_button.clicked.connect(self.toggle_logs)

        self.clean_button = self.make_icon_button('clear_console.png', 'Clear Output')
        self.clean_button.clicked.connect(self.clean_output)

        layout.addWidget(self.urls_box)
        layout.addWidget(self.endpoint_box)
        layout.addStretch()
        layout.addWidget(self.log_button)
        layout.addWidget(self.clean_button)

    @staticmethod
    def make_icon_button(icon_name, tooltip, checkable=False):
        button = QPushButton('')
        button.setCheckable(checkable)
        button.setToolTip(tooltip)
        icon_path = os.path.join(settings.COMFYUI2NUKE, 'icons', icon_name)
        button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(16, 16))
        return button

    @property
    def current_endpoint(self):
        return self.endpoint_box.currentText()

    def start_logs_ui(self, url):
        self.output_widget.start_log(url)
        self.log_button.setChecked(True)
        self.log_button.setText('Stop Logs')

    def reset_log_button_ui(self):
        self.log_button.setChecked(False)
        self.log_button.setText('')

    def on_url_changed(self, event):
        self.output_widget.stop_log()

        url = self.urls_box.currentText()
        if url == '-':
            self.reset_log_button_ui()
            self.output_widget.clear()
            return

        if self.current_endpoint == LOGS_ENDPOINT:
            self.start_logs_ui(url)
        else:
            self.output_widget.show_system_stats(url)

    def on_endpoint_changed(self, event):
        self.output_widget.stop_log()
        self.output_widget.clear()

        url = self.urls_box.currentText()
        is_logs = self.current_endpoint == LOGS_ENDPOINT
        self.log_button.setEnabled(is_logs)

        if url == '-':
            self.reset_log_button_ui()
            return

        if is_logs:
            self.start_logs_ui(url)
        else:
            self.reset_log_button_ui()
            self.output_widget.show_system_stats(url)

    def toggle_logs(self, checked):
        if self.current_endpoint != LOGS_ENDPOINT:
            self.log_button.setChecked(False)
            return

        url = self.urls_box.currentText()

        if checked and url == '-':
            self.log_button.setChecked(False)
            return

        if checked:
            self.start_logs_ui(url)
        else:
            self.output_widget.stop_log()
            self.log_button.setText('')

    def clean_output(self):
        self.output_widget.clear()


class output_widget(QTextEdit):
    MAX_LINES = 1000
    ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')
    ANSI_COLORS = {
        '30': (40, 44, 52),    '31': (224, 108, 117),
        '32': (152, 195, 121), '33': (229, 192, 123),
        '34': (97, 175, 239),  '35': (198, 120, 221),
        '36': (86, 182, 194),  '37': (215, 218, 224),
        '90': (92, 99, 112),   '91': (224, 108, 117),
        '92': (152, 195, 121), '93': (229, 192, 123),
        '94': (97, 175, 239),  '95': (198, 120, 221),
        '96': (86, 182, 194),  '97': (255, 255, 255),
    }
    DEFAULT_COLOR = (187, 187, 187)

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

    def start_log(self, url=None, last_timestamp=None):
        if self.poller and self.poller.is_running:
            return

        self.poller = LogPoller(url or settings.URL, error_callback=self.on_poller_error)
        if last_timestamp is not None:
            self.poller.last_timestamp = last_timestamp

        self.poller.start()
        self.poll_timer.start()

    def on_poller_error(self, message):
        self.poller.queue.put('__CLEAR__')
        self.poller.queue.put(ansi('31', 'Error: {}'.format(message)))

    def stop_log(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        self.poll_timer.stop()

    def show_system_stats(self, url):
        self.stop_log()
        self.clear()

        base_url = format_URLs(url)[0]

        try:
            full_url = '{}{}'.format(base_url, SYSTEM_STATS_PATH)
            data = fetch_json(full_url)
            text = format_json_ansi(data)
        except Exception as error:
            text = ansi('31', 'Error fetching system stats: {}'.format(error))

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.insert_ansi_text(cursor, text)
        self.setTextCursor(cursor)

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
            if msg == '__CLEAR__':
                self.clear()
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.End)
                continue
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

    def resume_log_from_latest(self, url):
        temp_poller = LogPoller(url)
        latest_ts = temp_poller.get_latest_timestamp()
        self.stop_log()
        self.start_log(url, last_timestamp=latest_ts)

    def hideEvent(self, event):
        super(output_widget, self).hideEvent(event)
        self.stop_log()

    def showEvent(self, event):
        super(output_widget, self).showEvent(event)
        parent = self.parent
        if not hasattr(parent, 'toolbar'):
            return

        toolbar = parent.toolbar
        if toolbar.current_endpoint != LOGS_ENDPOINT:
            return

        if toolbar.log_button.isChecked():
            url = toolbar.urls_box.currentText()
            self.resume_log_from_latest(url)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Backspace:
            self.clear()
            if self.poller:
                self.resume_log_from_latest(self.poller.url)
        QTextEdit.keyPressEvent(self, event)
