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

protocol = 'https' if PORT == 443 else 'http'

def GET(relative_url):
    url = '{}://{}:{}/{}'.format(protocol, IP, PORT, relative_url)
    request = urllib2.Request(url)
    request.add_header('User-Agent', 'Mozilla/5.0')

    try:
        response = urllib2.urlopen(request)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except:
        nuke.message(
            'Error connecting to server {} on port {} !'.format(IP, PORT))


def check_connection():
    try:
        url ='{}://{}:{}'.format(protocol, IP, PORT)
        request = urllib2.Request(url)
        request.add_header('User-Agent', 'Mozilla/5.0')

        response = urllib2.urlopen(request)
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
    url = '{}://{}:{}/upload/image'.format(protocol, IP, PORT)
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
    filename_prefix, sequence_output = filename

    ext = 'png'
    subfolder = os.path.basename(sequence_output)

    output = os.path.join(dst_folder, subfolder)
    if not os.path.exists(output):
        os.makedirs(output)

    last_frame = 0

    for i in range(1, 10000):
        image = '{}_{}_.{}'.format(filename_prefix, str(i).zfill(5), ext)

        url = '{}://{}:{}/api/view?filename={}&subfolder={}'.format(
            protocol, IP, PORT, image, subfolder)

        r = requests.get(url, stream=True)

        if r.status_code != 200:
            last_frame = i - 1
            break

        dst_path = os.path.join(output, image)

        with open(dst_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    return '{}/{}_#####_.{} 1-{}'.format(output, filename_prefix, ext, last_frame)


def POST(relative_url, data={}):
    url = '{}://{}:{}/{}'.format(protocol, IP, PORT, relative_url)
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0'
    }
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
