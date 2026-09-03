import json
import threading
from time import time

import nuke  # type: ignore
import websocket

from .common import execute_in_main_thread
from .connection import GET, get_ip_from_url
from .queue_manager import find_prompt_id, interrupt


class ComfyJob:
    def __init__(
        self,
        run_node,
        settings,
        node_update,
        client_id="",
        prompt_id=None,
    ):
        self.run_node = run_node
        self.settings = settings
        self.node_update = node_update
        self.client_id = client_id
        self.prompt_id = prompt_id
        self.data = None
        self.progress_title = "Inferencing"
        self.progress_value = 0
        self.progress_message = ""
        self.progress = nuke.ProgressTask(self.progress_title)
        self.finished = threading.Event()
        self.cancelled = False
        self.execution_error = ""
        self.prompt_was_queued = bool(prompt_id)
        self.websocket = None
        self.websocket_thread = None
        self.monitor_thread = None

    def set_progress(self, value, message="", include_ip=True):
        if not nuke.GUI:
            print("{} : {}%".format(message or self.progress_message, value))

        progress = self.progress
        if not progress:
            return

        progress.setProgress(value)
        self.progress_value = value

        if not message:
            return

        if "Loop" in message:
            message = "{} - {}".format(
                message.count("Loop") + 1,
                message.split(".")[-1],
            )

        ip = ""
        if include_ip and "127" not in self.settings["URL"]:
            ip = get_ip_from_url(self.settings["URL"])

        message = "{} ({}) ".format(message, ip) if ip else message
        progress.setMessage(message)
        self.progress_message = message

    def close_progress(self):
        self.progress = None

    def restore_progress(self):
        self.progress = nuke.ProgressTask(self.progress_title)
        self.progress.setProgress(self.progress_value)
        self.progress.setMessage(self.progress_message)

    def start_monitor(self):
        url = "{}/ws?clientId={}".format(
            self.settings["URL"].replace("http", "ws"),
            self.client_id,
        )
        self.websocket = websocket.WebSocketApp(
            url,
            on_message=self.handle_message,
            on_error=self.handle_websocket_error,
        )
        self.websocket_thread = threading.Thread(
            target=self.websocket.run_forever,
            daemon=True,
        )
        self.websocket_thread.start()
        self.monitor_thread = threading.Thread(
            target=self.monitor,
            daemon=True,
        )
        self.monitor_thread.start()

    def handle_message(self, websocket_client, message):
        try:
            if len(message) > 1024 * 200:
                self.set_progress(50, "Waiting to finish...")
                websocket_client.close()
                return
            message = json.loads(message)
        except Exception:
            return

        message_data = message.get("data") or {}
        if not message_data:
            return

        message_prompt_id = message_data.get("prompt_id")
        if self.prompt_id and message_prompt_id and message_prompt_id != self.prompt_id:
            return
        if message_prompt_id:
            self.prompt_id = message_prompt_id
            self.prompt_was_queued = True

        message_type = message.get("type")
        if message_type == "execution_start":
            self.settings["inference_time"] = time()
        elif message_type == "executed":
            node_name = message_data.get("node")
            execute_in_main_thread(
                self.node_update,
                args=(node_name, message_data, self.run_node, self.settings),
            )
        elif message_type == "progress":
            maximum = float(message_data.get("max") or 0.01)
            value = int(message_data.get("value", 0) * 100 / maximum)
            self.set_progress(value)
        elif message_type == "executing":
            node_name = message_data.get("node")
            if node_name:
                self.set_progress(0, node_name)
            else:
                self.close_progress()
                self.finished.set()
        elif message_type == "execution_error":
            self.execution_error = self.format_execution_error(message_data)
            self.report_error(self.execution_error, message_data)
            self.close_progress()
            self.finished.set()

    def handle_websocket_error(self, websocket_client, error):
        if "connected" in str(error):
            return

        websocket_client.close()
        self.execution_error = self.format_connection_error(error)
        self.report_error(self.execution_error)
        self.close_progress()
        self.finished.set()

    def format_execution_error(self, message_data):
        return message_data.get(
            "exception_message",
            "ComfyUI execution failed.",
        )

    def format_connection_error(self, error):
        return "Error: {}".format(error)

    def report_error(self, message, message_data=None):
        return None

    def handle_cancellation(self):
        progress = self.progress
        if not progress or not progress.isCancelled():
            return False

        confirmed = nuke.executeInMainThreadWithResult(
            lambda: nuke.ask("Are you sure? This will stop the ComfyUI inference")
        )
        if not confirmed:
            self.restore_progress()
            return False

        self.cancelled = True
        interrupt(self.settings, self.client_id)
        self.close_progress()
        self.finished.set()
        return True

    def update_queue_state(self):
        queue = GET("queue", self.settings, warning=False)
        if queue is None:
            return

        running = queue.get("queue_running", [])
        pending = queue.get("queue_pending", [])
        queue_items = running + pending

        if self.prompt_id:
            prompt_is_queued = any(
                len(item) > 1 and item[1] == self.prompt_id for item in queue_items
            )
        else:
            self.prompt_id = find_prompt_id(running, self.client_id)
            if not self.prompt_id:
                self.prompt_id = find_prompt_id(pending, self.client_id)
            prompt_is_queued = bool(self.prompt_id)

        if prompt_is_queued:
            self.prompt_was_queued = True
        elif self.prompt_was_queued:
            self.finished.set()

    def monitor(self):
        check_count = 0
        while not self.finished.wait(0.1):
            if self.handle_cancellation():
                break

            check_count += 1
            if check_count < 10:
                continue

            check_count = 0
            self.update_queue_state()

        self.close_progress()
        if self.websocket:
            self.websocket.close()

        self.cleanup()
        if self.cancelled:
            return

        execute_in_main_thread(self.finish)

    def set_external_error(self, error):
        self.execution_error = error
        self.close_progress()
        self.finished.set()

    def wait(self):
        if self.monitor_thread:
            self.monitor_thread.join()

    def cleanup(self):
        return None

    def finish(self):
        raise NotImplementedError("ComfyJob subclasses must implement finish().")
