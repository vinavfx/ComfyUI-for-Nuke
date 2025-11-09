# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import nuke  # type: ignore
import shutil
import requests

from .common import get_comfyui_dir, get_settings


def upload_images(folder, settings):
    task = nuke.ProgressTask('Uploading to ComfyUI')

    url = '{}/upload/image'.format(settings['URL'])
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

            resp = requests.post(
                url, headers=settings['HTTP_HEADER'], files=files, data=data)
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

        url = '{}/api/view?filename={}&subfolder={}'.format(
            settings['URL'], image, subfolder)

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


def upload_media():
    settings = get_settings()
    input_dir = os.path.join(get_comfyui_dir(settings), 'input')
    filepath = nuke.getFilename(
        'Upload Media', "*.jpg *.exr *.png *.mp3 *.wav")

    if not filepath:
        return

    this = nuke.thisNode()

    list_knob = this.knob('audio_')
    if not list_knob:
        list_knob = this.knob('image_')

    if not list_knob:
        return

    shutil.copy(filepath, input_dir)

    filename = os.path.basename(filepath)
    updated_options = list_knob.values()

    if not filename in updated_options:
        updated_options.append(filename)

    list_knob.setValues(updated_options)
    list_knob.setValue(filename)
