# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import json
import traceback
from collections import OrderedDict
import re

if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from .common import show_message, get_settings


def get_ip_from_url(url):
    if "://" in url:
        _, rest = url.split("://", 1)
    else:
        rest = url

    return rest.split(":")[0].split("/")[0]


def format_URLs(url, protocol=True):
    urls = []
    pattern = r"^(https?://)?([a-zA-Z0-9.-]+|\d{1,3}(\.\d{1,3}){3})(:\d{1,5})?$"

    if re.match(pattern, url):
        urls = [url]
    else:
        try:
            urls = json.loads(url)
        except:
            pass

    result = []
    for u in urls:
        if "://" not in u:
            u = "http://{}".format(u)
        if re.search(r":\d+$", u) is None:
            u += ":8188"
        if not protocol:
            u = u.split("://")[1]
        result.append(u)

    return result


def GET(endpoint, settings, warning=True, timeout=30):
    url = format_URLs(settings["URL"])[0]

    url = "{}/{}".format(url, endpoint)
    request = urllib2.Request(url)

    try:
        response = urllib2.urlopen(request, timeout=timeout)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except:
        if warning:
            show_message(f"Error connecting to ComfyUI server {settings['URL']}!")


def check_connection():
    if GET("system_stats", get_settings()):
        return True

    return False


def POST(endpoint, data, settings):
    url = "{}/{}".format(settings["URL"], endpoint)

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
                show_message("Error parsing JSON from server")
                return "ERROR: JSON parsing"

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
        except:
            show_message(traceback.format_exc())

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
    elif sys.version_info[0] < 3 and isinstance(data, unicode):
        return data.encode("utf-8")
    else:
        return data
