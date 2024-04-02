# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import json
import traceback

if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from ..settings import IP, PORT


def send_request(relative_url, data={}):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)
    headers = {'Content-Type': 'application/json'}
    request = urllib2.Request(url, json.dumps(data), headers)  # type: ignore

    try:
        urllib2.urlopen(request)
        return ''

    except urllib2.HTTPError as e:
        try:
            error = json.loads(e.read())
            errors = 'ERROR: {}\n\n'.format(error['error']['message'].upper())

            for name, value in error['node_errors'].items():
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


def interrupt():
    error = send_request('interrupt')

    if error:
        nuke.message(error)
