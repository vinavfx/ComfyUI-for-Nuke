# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import json
import traceback
from collections import OrderedDict

if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from ..env import IP, PORT


def GET(relative_url):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)

    try:
        response = urllib2.urlopen(url)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except:
        nuke.message(
            'Error connecting to server {} on port {} !'.format(IP, PORT))


def POST(relative_url, data={}):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)
    headers = {'Content-Type': 'application/json'}
    bytes_data = json.dumps(data).encode('utf-8')
    request = urllib2.Request(url, bytes_data, headers)

    try:
        urllib2.urlopen(request)
        return ''

    except urllib2.HTTPError as e:
        try:
            error_str = str(e.read()).strip()
            if not error_str:
                nuke.message(traceback.format_exc())
                return 'ERROR: HTTPError'

            error = json.loads(error_str)
            errors = 'ERROR: {}\n\n'.format(error['error']['message'].upper())
            node_errors = error['node_errors'] if error['node_errors'] else {}

            for name, value in node_errors.items():
                nuke.toNode(name).setSelected(True)
                errors += '{}:\n'.format(name)

                for err in value['errors']:
                    errors += ' - {}: {}\n'.format(
                        err['details'], err['message'])

                errors += '\n'

            return errors
        except:
            nuke.message(traceback.format_exc())

    except Exception as e:
        return 'Error: {}'.format(e)


def convert_to_utf8(data):
    if isinstance(data, dict):
        return {convert_to_utf8(key): convert_to_utf8(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_to_utf8(element) for element in data]
    elif isinstance(data, str):
        return data.encode('utf-8') if sys.version_info[0] < 3 else data
    elif sys.version_info[0] < 3 and isinstance(data, unicode):
        return data.encode('utf-8')
    else:
        return data


def interrupt():
    error = POST('interrupt')

    if error:
        nuke.message(error)
