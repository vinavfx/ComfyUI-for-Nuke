# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import shutil
import nuke  # type: ignore

from ..nuke_util.media_util import get_padding, get_name_no_padding
from ..nuke_util.nuke_util import get_output_nodes
from .nodes import get_connected_comfyui_nodes, get_input
from .common import get_date_code
from .upload_and_download import download_images
from .update_menu import normalize_nodename


def exr_filepath_fixed(run_node):
    nodes = get_connected_comfyui_nodes(run_node)
    for n, _ in nodes:
        filepath_knob = n.knob("filepath_")
        if not filepath_knob:
            continue

        filepath = filepath_knob.value()
        padding = get_padding(filepath)
        if not padding:
            continue

        filepath = filepath.replace(padding, "%04d")
        filepath_knob.setText(filepath)


def get_tonemap(run_node):
    save_node = get_input(run_node, 0)

    if not save_node:
        return "sRGB"

    tonemap_knob = save_node.knob("tonemap_")
    if not tonemap_knob:
        return "sRGB"

    return tonemap_knob.value()


def update_filename_prefix(run_node, update=True, data={}):
    output_node = get_input(run_node, 0)
    if not output_node:
        return

    filename_prefix_knob = output_node.knob("filename_prefix_")
    if not filename_prefix_knob:
        return

    if not update:
        return filename_prefix_knob.value()

    prefix = filename_prefix_knob.value()
    old_rand = prefix.split("/")[0]

    if old_rand.isdigit():
        prefix = prefix.replace(old_rand + "/", "")

    new_prefix = "{}/{}".format(get_date_code(), prefix)
    filename_prefix_knob.setValue(new_prefix)
    data[output_node.name()]["inputs"]["filename_prefix"] = new_prefix
    return new_prefix


def set_correct_colorspace(read):
    filename = read.knob("file").value()
    ext = filename.split(".")[-1]

    if ext == "exr":
        read.knob("raw").setValue(True)
    else:
        read.knob("raw").setValue(False)


def get_gizmo_group(run_node):
    gizmo = run_node

    while gizmo:
        gizmo = gizmo.parent()
        if not hasattr(gizmo, "knob"):
            return

        if gizmo.knob("comfyui_gizmo"):
            return gizmo


def extract_meta(data):
    noise_seed = seed = steps = denoise = guidance = causvid = strength = -1
    scheduler = sampler_name = lora = lora2 = lora3 = cnet = ""

    for name, node in data.items():
        class_type = node["class_type"]
        inputs = node["inputs"]

        if noise_seed == -1:
            noise_seed = inputs.get("noise_seed", -1)

        if seed == -1:
            seed = inputs.get("seed", -1)

        if not sampler_name:
            sampler_name = inputs.get("sampler_name", "")

        if steps == -1:
            steps = inputs.get("steps", -1)

        if denoise == -1:
            denoise = inputs.get("denoise", -1)

        if not scheduler:
            scheduler = inputs.get("scheduler", "")

        if guidance == -1:
            guidance = inputs.get("guidance", -1)

        if causvid == -1:
            lora_name = inputs.get("lora_name", "")
            if "CausVid" in lora_name:
                causvid = inputs.get("strength_model", 0)

        if class_type == "WanVaceToVideo":
            strength = inputs.get("strength")

        if name in ("extra_lora1", "extra_lora2", "extra_lora3"):
            lora_name = inputs.get("lora_name", "").split("/")[-1].rsplit(".", 1)[0]
            lora_strength = inputs.get("strength_model", 0)
            formatted = "{}:{}".format(lora_name, lora_strength)

            if name == "extra_lora1":
                lora = formatted
            elif name == "extra_lora2":
                lora2 = formatted
            elif name == "extra_lora3":
                lora3 = formatted

        if class_type == "ControlNetApplyAdvanced":
            cnet_strength = inputs.get("strength", 0)
            cnet_end = inputs.get("end_percent", 0)
            cnet = "{} : {}".format(cnet_strength, cnet_end)

    meta = []

    if not seed == -1:
        meta.append(("seed", seed))

    if not noise_seed == -1:
        meta.append(("noise_seed", noise_seed))

    if not steps == -1:
        meta.append(("steps", steps))

    if sampler_name:
        meta.append(("sampler_name", sampler_name))

    if scheduler:
        meta.append(("scheduler", scheduler))

    if not denoise == -1:
        meta.append(("denoise", denoise))

    if not guidance == -1:
        meta.append(("guidance", guidance))

    if not strength == -1:
        meta.append(("strength", strength))

    if not causvid == -1:
        meta.append(("causvid", causvid))

    if cnet:
        meta.append(("CNet", cnet))

    if lora:
        meta.append(("lora", lora))

    if lora2:
        meta.append(("lora2", lora2))

    if lora3:
        meta.append(("lora3", lora3))

    return meta


def glb2obj(filename):
    import trimesh  # type: ignore

    mesh = trimesh.load(filename)
    obj = filename[:-3] + "obj"
    mesh.export(obj)

    read = nuke.createNode("ReadGeo", inpanel=False)
    read.knob("file").setValue(obj)
    read.setInput(0, None)

    return read


def get_frame_range(data):
    #  Of all the read nodes, it gets the longest range.
    ranges = [n.get("frame_range") for n in data.values() if n.get("frame_range")]
    if not ranges:
        return [1, 1]
    return max(ranges, key=lambda r: r[1] - r[0])


def get_output_path(settings, default_output=False):
    default_output_dir = os.path.join(settings["COMFYUI_DIR"], "output")

    if default_output:
        return default_output_dir

    output_dir = settings["OUTPUT_DIRECTORY"].strip()
    untitled = settings["project_name"] == "Root"

    if os.path.isabs(output_dir) and os.path.isdir(output_dir):
        return output_dir

    elif output_dir and not untitled:
        return os.path.join(os.path.dirname(settings["project_name"]), output_dir)

    elif settings["COMFYUI_LOCAL"] and not untitled:
        return default_output_dir

    return os.path.join(settings["TEMPORAL_DIR"], "output")


def relocate_filename(filename, settings):
    if not settings["OUTPUT_DIRECTORY"].strip():
        return filename

    if not filename:
        return

    task = nuke.ProgressTask("Relocate from ComfyUI")
    task.setMessage("Relocating: ...")
    task.setProgress(0)

    output_dir = get_output_path(settings)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    src_dir = os.path.dirname(filename)
    dst_dir = os.path.join(output_dir, os.path.basename(src_dir))

    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)

    os.mkdir(dst_dir)
    files = os.listdir(src_dir)

    for i, f in enumerate(files):
        src_file = os.path.join(src_dir, f)
        if os.path.isfile(src_file):
            shutil.move(src_file, dst_dir)

        task.setMessage("Relocating: " + f)
        task.setProgress(int((i / float(len(files))) * 100))

    task.setProgress(100)

    return os.path.join(dst_dir, os.path.basename(filename))


def get_separate_filename(settings, default_output=False):
    filename_prefix = settings.get("filename_prefix")

    if filename_prefix:
        basename = os.path.basename(filename_prefix)
        dirname = os.path.dirname(filename_prefix)

        sequence_output = os.path.join(
            get_output_path(settings, default_output), dirname
        )

        return filename_prefix, basename, sequence_output

    else:
        return None, None, None


def get_local_filename(settings, default_output=False):
    _, basename, sequence_output = get_separate_filename(settings, default_output)

    if not sequence_output:
        return

    filenames = nuke.getFileNameList(sequence_output)
    if not filenames:
        return

    filename = next((fn for fn in filenames if basename in fn), None)

    if not filename:
        return

    return os.path.join(sequence_output, filename)


def resolve_filename(run_node, data, settings, already_generated=False):
    if settings["COMFYUI_LOCAL"]:
        if already_generated:
            filename = get_local_filename(settings)
        else:
            filename = get_local_filename(settings, default_output=True)
            filename = relocate_filename(filename, settings)
    else:
        output_dir = get_output_path(settings)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        filename = download_images(
            get_separate_filename(settings),
            output_dir,
            get_frame_range(data),
            settings,
            run_node,
        )

    return filename


def create_read(run_node, data, settings, filename, already_exists=False):
    if not filename:
        return

    if not already_exists:
        backup_previous_generation(run_node)

    meta = []
    if data:
        meta = extract_meta(data)

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()

    fullname = "{}Read".format(main_node.fullName())
    name = "{}Read".format(main_node.name())
    ext = filename.split(".")[-1].split(" ")[0].lower()

    if ext in ["jpg", "exr", "tiff", "png"]:
        read = nuke.toNode(fullname)
        if not read:
            read = nuke.createNode("Read", inpanel=False)

        read.knob("file").fromUserText(filename)
        read.knob("frame_mode").setValue("start at")
        read.knob("frame").setValue(str(get_frame_range(data)[0]))

        set_correct_colorspace(read)

    elif ext in ["glb"]:
        read = glb2obj(filename)

    else:
        return

    read.setName(name)
    read.setXYpos(main_node.xpos(), main_node.ypos() + 35)
    read.knob("tile_color").setValue(main_node.knob("tile_color").value())

    label = ""
    if meta and settings["DISPLAY_META_IN_READ_NODE"]:
        label = "<center>"
        for key, value in meta:
            label += '<font color="green" size=1>{}:</font><font color="white" size=1> {}</>\n'.format(
                key, value
            )

    read.knob("label").setValue(label)

    comfyui_gizmo = (
        run_node.parent() if run_node.parent().knob("comfyui_gizmo") else run_node
    )

    for i, onode in get_output_nodes(comfyui_gizmo):
        onode.setInput(i, read)

    return read


def backup_previous_generation(run_node=None):
    if not run_node:
        run_node = nuke.thisNode()

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()

    read = nuke.toNode(main_node.name() + "Read")
    if not read:
        return

    filename = "{} {}-{}".format(
        read.knob("file").value(), read.knob("first").value(), read.knob("last").value()
    )

    basename = get_name_no_padding(filename).replace(" ", "_")
    rand = os.path.basename(os.path.dirname(filename)).strip()
    name = "{}Backup_{}_{}".format(main_node.name(), rand, basename)
    name = normalize_nodename(name)

    if not nuke.toNode(name):
        new_read = nuke.createNode("Read", inpanel=False)
        new_read.setName(name)
        new_read.knob("file").fromUserText(filename)
        new_read.knob("label").setValue(read.knob("label").value())
        new_read.knob("frame_mode").setValue(read.knob("frame_mode").value())
        new_read.knob("frame").setValue(read.knob("frame").value())
        set_correct_colorspace(new_read)

    reads = sorted(
        [
            n
            for n in nuke.allNodes("Read")
            if n.name().split("Backup")[0] == main_node.name()
        ],
        key=lambda n: n.name(),
        reverse=True,
    )

    xpos = read.xpos() + 150
    ypos = read.ypos()

    offset_x = 100
    offset_y = 20 + max(reads, key=lambda n: n.screenHeight()).screenHeight()
    per_row = 10

    for i, n in enumerate(reads):
        col = i % per_row
        row = i // per_row
        n.setXYpos(xpos + col * offset_x, ypos + row * offset_y)
