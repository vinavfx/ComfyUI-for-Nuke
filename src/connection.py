# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import os
import json
import traceback
from collections import OrderedDict
import requests


if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from ..settings import IP, PORT


def GET(relative_url):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)

    try:
        response = urllib2.urlopen(url)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except:
        nuke.message(
            'Error connecting to server {} on port {} !'.format(IP, PORT))


def check_connection():
    try:
        response = urllib2.urlopen('http://{}:{}'.format(IP, PORT))
        if response.getcode() == 200:
            return True
    except:
        nuke.message(
            'Error connecting to server {} on port {} !'.format(IP, PORT))
        return


def queue_running():
    queue = GET('queue')
    if not queue:
        return False

    running = queue['queue_running']
    pending = queue['queue_pending']

    if running or pending:
        if nuke.ask('Processes running, wait or interrupt to send new processes\n\nRunning: {}\nPending: {}\n\n interrupt?'.format(len(running), len(pending))):
            interrupt()

        return True

    return False


def upload_images(folder):
    url = 'http://{}:{}/upload/image'.format(IP, PORT)
    results = []

    for f in os.listdir(folder):
        image_path = os.path.join(folder, f)

        with open(image_path, 'rb') as f:
            files = {'image': f}
            data = {
                'subfolder': os.path.basename(folder),
                'overwrite': 'true'
            }
            resp = requests.post(url, files=files, data=data)
            results.append((resp.status_code, resp.text))

    return results


def download_images(filename, dst_folder):
    fn, frange = filename.rsplit(' ', 1)
    basename = os.path.basename(fn)

    clean_name = basename.rsplit('_#####', 1)[0]
    ext = fn.split('.')[-1]

    subfolder = os.path.basename(os.path.dirname(fn))
    first_frame, last_frame = [int(x) for x in frange.split('-')]

    output = os.path.join(dst_folder, subfolder)
    if not os.path.exists(output):
        os.makedirs(output)

    for i in range(first_frame, last_frame + 1):
        image = '{}_{}_.{}'.format(clean_name, str(i).zfill(5), ext)

        url = 'http://{}:{}/api/view?filename={}&subfolder={}'.format(
            IP, PORT, image, subfolder)

        r = requests.get(url, stream=True)
        if r.status_code != 200:
            nuke.message('Error in image download!\n{}'.format(r.status_code))

        dst_path = os.path.join(output, image)

        with open(dst_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    return '{}/{}_#####_.{} {}'.format(output, clean_name, ext, frange)


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
            error_bytes = e.read()
            error_str = error_bytes.decode('utf-8', errors='ignore').strip()

            try:
                error = json.loads(error_str)
            except json.JSONDecodeError:
                nuke.message('Error parsing JSON from server')
                return 'ERROR: JSON parsing'

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
