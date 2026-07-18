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
import nukescripts  # type: ignore
from ..nuke_util.panels import panel_widget
from ..nuke_util import panels
from ..nuke_util.pyside import (QVBoxLayout, QTextEdit, QWidget, QTimer,
                                QHBoxLayout, QPushButton, Qt,
                                QComboBox, QFont, QTextCursor, QTextCharFormat,
                                QColor, QIcon, QSize)
from .. import settings
from .connection import format_URLs
from .common import get_settings
from .queue_manager import scan_urls, job_running_message

panels.init('comfyui.console.console_panel', 'ComfyUI Console')

LOGS_ENDPOINT = 'Logs'
SYSTEM_STATS_ENDPOINT = 'System Stats'
QUEUE_ENDPOINT = 'Queue'
LOGS_RAW_PATH = '/internal/logs/raw'
SYSTEM_STATS_PATH = '/system_stats'
CLEAR_SENTINEL = '__CLEAR__'


def show_console():
    console = nuke.panels['comfyui_console']()

    if not console.isVisible():
        console_pane = nukescripts.restorePanel('comfyui_console')
        pane = nuke.getPaneFor('Properties.1')
        if pane:
            console_pane.addToPane(pane)

    if console.toolbar.urls_box.currentIndex() == 0:
        console.toolbar.urls_box.setCurrentIndex(1)


def fetch_json(url, timeout=2):
    response = urllib_request.urlopen(url, timeout=timeout)
    return json.loads(response.read().decode())


def ansi(code, text):
    return '\x1b[{}m{}\x1b[0m'.format(code, text)


def transform_memory_values(data):
    memory_keys = {'ram_total', 'ram_free', 'vram_total', 'vram_free',
                   'torch_vram_total', 'torch_vram_free'}

    def bytes_to_gb(value):
        if isinstance(value, (int, float)):
            return '{} GB'.format(round(value / (1024 ** 3), 2))
        return value

    if isinstance(data, dict):
        return {k: bytes_to_gb(v) if k in memory_keys else transform_memory_values(v)
                for k, v in data.items()}

    if isinstance(data, list):
        return [transform_memory_values(item) for item in data]

    return data


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
            lines.append('{}{}: {}{}'.format(
                pad_in, key_str, value_str, comma))
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


class Poller:
    POLL_INTERVAL = 1

    def __init__(self, url='127.0.0.1:8188', maxsize=1):
        self.url = format_URLs(url)[0]
        self.queue = queue.Queue(maxsize=maxsize)
        self.stop_event = threading.Event()
        self.thread = None
        self.last_error = None
        self.last_text = None

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

    def put_latest(self, text):
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(text)
        except queue.Full:
            pass

    def get_latest(self):
        latest = None
        while True:
            try:
                latest = self.queue.get_nowait()
            except queue.Empty:
                break
        return latest

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
                self.fetch()
                self.last_error = None
            except Exception as e:
                error_msg = str(e)
                if self.last_error != error_msg:
                    self.last_error = error_msg
                    self.put_latest(ansi('31', 'Error: {}'.format(error_msg)))
            self.stop_event.wait(self.POLL_INTERVAL)

    def fetch(self):
        pass


class LogPoller(Poller):
    def __init__(self, url='127.0.0.1:8188'):
        super().__init__(url, maxsize=0)
        self.last_timestamp = None

    def poll_loop(self):
        while not self.stop_event.is_set():
            try:
                self.fetch()
                self.last_error = None
            except Exception as e:
                error_msg = str(e)
                if self.last_error != error_msg:
                    self.last_error = error_msg
                    self.queue.put(CLEAR_SENTINEL)
                    self.queue.put(ansi('31', 'Error: {}'.format(error_msg)))
            self.stop_event.wait(self.POLL_INTERVAL)

    def fetch(self):
        url = '{}{}'.format(self.url, LOGS_RAW_PATH)
        data = fetch_json(url)

        for entry in data.get('entries', []):
            timestamp = entry.get('t', '')
            message = entry.get('m', '')

            if self.last_timestamp and timestamp <= self.last_timestamp:
                continue

            self.last_timestamp = timestamp
            self.queue.put(message)

    def get_latest_timestamp(self):
        try:
            url = '{}{}'.format(self.url, LOGS_RAW_PATH)
            entries = fetch_json(url).get('entries', [])
            if entries:
                return entries[-1].get('t', '')
        except Exception:
            pass
        return None


class StatsPoller(Poller):
    def fetch(self):
        full_url = '{}{}'.format(self.url, SYSTEM_STATS_PATH)
        data = fetch_json(full_url)
        data = transform_memory_values(data)
        text = format_json_ansi(data)
        if text != self.last_text:
            self.last_text = text
            self.put_latest(text)


class QueuePoller(Poller):
    def fetch(self):
        settings = get_settings()
        settings['URL'] = self.url
        _, _, _, running_client, pending_client = scan_urls(settings)
        text = job_running_message(running_client, pending_client)
        if text != self.last_text:
            self.last_text = text
            self.put_latest(text)


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
        self.urls_box.addItems(
            ['-'] + format_URLs(get_settings()['URL'], protocol=False))
        self.urls_box.currentIndexChanged.connect(self.on_url_changed)

        self.endpoint_box = QComboBox()
        self.endpoint_box.addItems([LOGS_ENDPOINT, SYSTEM_STATS_ENDPOINT, QUEUE_ENDPOINT])
        self.endpoint_box.currentIndexChanged.connect(self.on_endpoint_changed)

        self.log_button = QPushButton('Start')
        self.log_button.setCheckable(True)
        self.log_button.setToolTip('Start and Stop')
        icon_path = os.path.join(settings.COMFYUI2NUKE, 'icons', 'start.png')
        self.log_button.setIcon(QIcon(icon_path))
        self.log_button.setIconSize(QSize(16, 16))
        self.log_button.clicked.connect(self.toggle_polling)

        self.clean_button = QPushButton()
        self.clean_button.setToolTip('Clear Output')
        icon_path = os.path.join(settings.COMFYUI2NUKE, 'icons', 'clear_console.png')
        self.clean_button.setIcon(QIcon(icon_path))
        self.clean_button.setIconSize(QSize(16, 16))
        self.clean_button.clicked.connect(self.clean_output)

        layout.addWidget(self.urls_box)
        layout.addWidget(self.endpoint_box)
        layout.addStretch()
        layout.addWidget(self.log_button)
        layout.addWidget(self.clean_button)

    @property
    def current_endpoint(self):
        return self.endpoint_box.currentText()

    def set_button_running(self, running):
        if running:
            icon_path = os.path.join(settings.COMFYUI2NUKE, 'icons', 'stop.png')
            self.log_button.setText(' Stop')
        else:
            icon_path = os.path.join(settings.COMFYUI2NUKE, 'icons', 'start.png')
            self.log_button.setText('Start')
        self.log_button.setIcon(QIcon(icon_path))
        self.log_button.setChecked(running)

    def start_logs_ui(self, url):
        self.output_widget.clear()
        self.output_widget.last_log_timestamp = None
        self.output_widget.start_log(url)
        self.set_button_running(True)

    def reset_log_button_ui(self):
        self.set_button_running(False)

    def on_url_changed(self, _):
        self.output_widget.stop_all()

        url = self.urls_box.currentText()
        if url == '-':
            self.reset_log_button_ui()
            self.output_widget.clear()
            return

        endpoint = self.current_endpoint
        if endpoint == LOGS_ENDPOINT:
            self.start_logs_ui(url)
        elif endpoint == QUEUE_ENDPOINT:
            self.output_widget.start_queue(url)
            self.set_button_running(True)
        else:
            self.output_widget.start_stats(url)
            self.set_button_running(True)

    def on_endpoint_changed(self, _):
        self.output_widget.stop_all()
        self.output_widget.clear()

        url = self.urls_box.currentText()

        if url == '-':
            self.reset_log_button_ui()
            return

        endpoint = self.current_endpoint
        if endpoint == LOGS_ENDPOINT:
            self.start_logs_ui(url)
        elif endpoint == QUEUE_ENDPOINT:
            self.output_widget.start_queue(url)
            self.set_button_running(True)
        else:
            self.output_widget.start_stats(url)
            self.set_button_running(True)

    def toggle_polling(self, checked):
        url = self.urls_box.currentText()

        if checked and url == '-':
            self.set_button_running(False)
            return

        endpoint = self.current_endpoint
        if checked:
            if endpoint == LOGS_ENDPOINT:
                self.start_logs_ui(url)
            elif endpoint == QUEUE_ENDPOINT:
                self.output_widget.start_queue(url)
                self.set_button_running(True)
            else:
                self.output_widget.start_stats(url)
                self.set_button_running(True)
        else:
            self.output_widget.stop_all()
            self.set_button_running(False)

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
    PROGRESS_RE = re.compile(r'\d{1,3}%\|.*\|\s*\d+/\d+')

    def __init__(self, parent):
        QTextEdit.__init__(self, parent)
        self.parent = parent
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(self.MAX_LINES)
        self.poller = None
        self.stats_poller = None
        self.queue_poller = None
        self.last_log_timestamp = None
        self.last_line_was_progress = False

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

        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(500)
        self.stats_timer.timeout.connect(self.flush_stats_to_ui)

        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(500)
        self.queue_timer.timeout.connect(self.flush_queue_to_ui)

    def start_log(self, url=None, last_timestamp=None):
        self.stop_stats()
        self.stop_queue()

        if self.poller and self.poller.is_running:
            return

        self.poller = LogPoller(url or settings.URL)
        ts = last_timestamp if last_timestamp is not None else self.last_log_timestamp
        if ts is not None:
            self.poller.last_timestamp = ts

        self.poller.start()
        self.poll_timer.start()

    def stop_log(self):
        if self.poller:
            self.last_log_timestamp = self.poller.last_timestamp
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
            if msg == CLEAR_SENTINEL:
                self.clear()
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.last_line_was_progress = False
                continue

            clean_msg = msg.replace('\r', '').rstrip('\n')
            is_progress = bool(self.PROGRESS_RE.search(clean_msg))

            if is_progress and self.last_line_was_progress:
                cursor.movePosition(QTextCursor.StartOfBlock)
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
            elif not cursor.atBlockStart():
                cursor.insertText('\n')

            self.insert_ansi_text(cursor, clean_msg)
            self.last_line_was_progress = is_progress

        self.setTextCursor(cursor)

        if was_at_bottom:
            QTimer.singleShot(0, self.scroll_to_bottom)

    def resume_log_from_latest(self, url):
        temp_poller = LogPoller(url)
        latest_ts = temp_poller.get_latest_timestamp()
        self.stop_log()
        self.start_log(url, last_timestamp=latest_ts)

    def start_stats(self, url=None):
        self.stop_log()
        self.stop_queue()

        if self.stats_poller and self.stats_poller.is_running:
            return

        self.clear()
        self.stats_poller = StatsPoller(url or settings.URL)
        self.stats_poller.start()
        self.stats_timer.start()

    def stop_stats(self):
        if self.stats_poller:
            self.stats_poller.stop()
            self.stats_poller = None
        self.stats_timer.stop()

    def flush_stats_to_ui(self):
        if not self.stats_poller:
            return

        text = self.stats_poller.get_latest()
        if text is None:
            return

        self.replace_all_ansi_text(text)

    def start_queue(self, url=None):
        self.stop_log()
        self.stop_stats()

        if self.queue_poller and self.queue_poller.is_running:
            return

        self.clear()
        self.queue_poller = QueuePoller(url or settings.URL)
        self.queue_poller.start()
        self.queue_timer.start()

    def stop_queue(self):
        if self.queue_poller:
            self.queue_poller.stop()
            self.queue_poller = None
        self.queue_timer.stop()

    def flush_queue_to_ui(self):
        if not self.queue_poller:
            return

        text = self.queue_poller.get_latest()
        if text is None:
            return

        self.setHtml(text)

    def replace_all_ansi_text(self, text):
        v_scroll = self.verticalScrollBar()
        h_scroll = self.horizontalScrollBar()
        v_value = v_scroll.value()
        h_value = h_scroll.value()

        self.clear()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.insert_ansi_text(cursor, text)
        self.setTextCursor(cursor)

        v_scroll.setValue(v_value)
        h_scroll.setValue(h_value)

    def stop_all(self):
        self.stop_log()
        self.stop_stats()
        self.stop_queue()

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

    def scroll_to_bottom(self):
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def hideEvent(self, event):
        super(output_widget, self).hideEvent(event)
        self.stop_all()

    def showEvent(self, event):
        super(output_widget, self).showEvent(event)
        parent = self.parent
        if not hasattr(parent, 'toolbar'):
            return

        toolbar = parent.toolbar
        url = toolbar.urls_box.currentText()
        if url == '-':
            return

        if not toolbar.log_button.isChecked():
            return

        endpoint = toolbar.current_endpoint
        if endpoint == LOGS_ENDPOINT:
            self.start_log(url)
        elif endpoint == QUEUE_ENDPOINT:
            self.start_queue(url)
        else:
            self.start_stats(url)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Backspace:
            self.clear()
            if self.poller:
                self.resume_log_from_latest(self.poller.url)
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.scroll_to_bottom()
            event.ignore()
            return

        if event.key() == Qt.Key_Space:
            event.ignore()
            return

        QTextEdit.keyPressEvent(self, event)
