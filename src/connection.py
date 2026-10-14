# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import json
import traceback
from collections import OrderedDict
from urllib.parse import urlsplit

if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from .common import show_message


def get_hostname_from_url(url):
    return urlsplit(url if "://" in url else "//" + url).hostname or ""


def GET(endpoint, settings, warning=True, timeout=30):
    url = settings["URL"][0]

    url = "{}/{}".format(url, endpoint)
    request = urllib2.Request(url)

    try:
        response = urllib2.urlopen(request, timeout=timeout)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except Exception:
        if warning:
            show_message(f"Error connecting to ComfyUI server {settings['URL']}!")


def POST(endpoint, data, settings):
    url = "{}/{}".format(settings["URL"][0], endpoint)

    bytes_data = json.dumps(data).encode("utf-8")
    request = urllib2.Request(url, bytes_data)

    try:
        urllib2.urlopen(request)
        return ""

    except urllib2.HTTPError as e:
        try:
            error_bytes = e.read()
            error_str = error_bytes.decode("utf-8", errors="ignore").strip()

            try:
                error = json.loads(error_str)
            except json.JSONDecodeError:
                message = "ERROR: HTTP {} FROM {}".format(e.code, url)
                if error_str:
                    message += "\n\n{}".format(error_str)
                show_message(message)
                return message

            errors = "ERROR: {}\n\n".format(error["error"]["message"].upper())
            node_errors = error["node_errors"] if error["node_errors"] else {}

            for name, value in node_errors.items():
                node = nuke.thisNode().parent().node(name)
                if node:
                    node.setSelected(True)

                errors += "{}:\n".format(name)

                for err in value["errors"]:
                    errors += " - {}: {}\n".format(err["details"], err["message"])

                errors += "\n"

            return errors
        except Exception:
            message = "ERROR: HTTP {} FROM {}\n\n{}".format(
                e.code, url, traceback.format_exc()
            )
            show_message(message)
            return message

    except Exception as e:
        return "Error: {}".format(e)


def convert_to_utf8(data):
    if isinstance(data, dict):
        return {
            convert_to_utf8(key): convert_to_utf8(value) for key, value in data.items()
        }
    elif isinstance(data, list):
        return [convert_to_utf8(element) for element in data]
    elif isinstance(data, str):
        return data.encode("utf-8") if sys.version_info[0] < 3 else data
    elif sys.version_info[0] < 3 and data.__class__.__name__ == "unicode":
        return data.encode("utf-8")
    else:
        return data
