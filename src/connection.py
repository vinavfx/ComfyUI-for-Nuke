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


def GET(relative_url, settings):
    url = '{}://{}:{}/{}'.format(settings['PROTOCOL'],
                                 settings['IP'], settings['PORT'], relative_url)

    request = urllib2.Request(url, headers=settings['HTTP_HEADER'])

    try:
        response = urllib2.urlopen(request)
        data = response.read().decode()
        return json.loads(data, object_pairs_hook=OrderedDict)
    except:
        nuke.message(
            'Error connecting to server {} on port {} !'.format(settings['IP'], settings['PORT']))


def check_connection(settings):
    if not GET('system_stats', settings):
        return False

    return True


def queue_running(settings):
    queue = GET('queue', settings)
    if not queue:
        return False

    running = queue['queue_running']
    pending = queue['queue_pending']

    if running or pending:
        if nuke.ask('Processes running, wait or interrupt to send new processes\n\nRunning: {}\nPending: {}\n\n interrupt?'.format(len(running), len(pending))):
            interrupt(settings)

        return True

    return False


def upload_images(folder, settings):
    task = nuke.ProgressTask('Uploading to ComfyUI')

    url = '{}://{}:{}/upload/image'.format(
        settings['PROTOCOL'], settings['IP'], settings['PORT'])
    results = []
    files = os.listdir(folder)
    total = len(files)

    for i, file in enumerate(files):
        image_path = os.path.join(folder, file)

        with open(image_path, 'rb') as f:
            files = {'image': f}
            data = {
                'subfolder': os.path.basename(folder),
                'overwrite': 'true'
            }

            resp = requests.post(url, headers=settings['HTTP_HEADER'], files=files, data=data)
            results.append((resp.status_code, resp.text))

        task.setMessage('Uploading: ' + file)
        task.setProgress(int((i / float(total)) * 100))

    task.setProgress(100)

    return results


def download_images(filename, dst_folder, frange, settings, run_node):
    from .nodes import get_node_data
    filename_prefix, sequence_output = filename

    from .nodes import get_input
    save_node = get_input(run_node, 0)
    class_type = ''
    if save_node:
        save_node_data = get_node_data(save_node)
        class_type = save_node_data['class_type']

    ext_map = {
        'SaveEXR': 'exr',
        'SaveGLB': 'glb',
        'SaveImage': 'png'
    }

    ext = ext_map.get(class_type, None)
    if not ext:
        return ''

    subfolder = os.path.basename(sequence_output)

    output = os.path.join(dst_folder, subfolder)
    if not os.path.exists(output):
        os.makedirs(output)

    last_frame = 0
    task = nuke.ProgressTask('Downloading from ComfyUI')
    task.setMessage('Downloading: ...')
    task.setProgress(0)
    total = frange[1] - frange[0] + 1
    downloaded = 0

    for i in range(1, 10000):
        image = '{}_{}_.{}'.format(filename_prefix, str(i).zfill(5), ext)

        url = '{}://{}:{}/api/view?filename={}&subfolder={}'.format(
            settings['PROTOCOL'], settings['IP'], settings['PORT'], image, subfolder)

        r = requests.get(url, headers=settings['HTTP_HEADER'], stream=True)

        if r.status_code != 200:
            last_frame = i - 1
            break

        if task.isCancelled():
            return

        dst_path = os.path.join(output, image)

        with open(dst_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        downloaded += 1

        task.setMessage('Downloading: ' + image)
        task.setProgress(int((i / float(total)) * 100))

    task.setProgress(100)

    if not downloaded:
        return

    return '{}/{}_#####_.{} 1-{}'.format(output, filename_prefix, ext, last_frame)


def POST(relative_url, data, settings):
    url = '{}://{}:{}/{}'.format(settings['PROTOCOL'],
                                 settings['IP'], settings['PORT'], relative_url)
    headers = {'Content-Type': 'application/json'}
    headers.update(settings['HTTP_HEADER'])

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


def interrupt(settings):
    error = POST('interrupt', {}, settings)

    if error:
        nuke.message(error)
