# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import math
import shutil
import nuke  # type: ignore
from time import time

from ..nuke_util.media_util import get_padding, get_name_no_padding
from ..nuke_util.nuke_util import get_output_nodes, selected_node, set_tile_color, get_tile_color
from .nodes import get_connected_comfyui_nodes, get_input
from .common import get_date_code, jsonloads, jsondumps, show_message
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


def update_filename_prefix(run_node, update=True, data={}):
    output_node = get_input(run_node, 0)
    if not output_node:
        return

    filename_prefix_knob = None
    filename_knob_name = ""

    for knob_name in ["filename_prefix", "file_path"]:
        filename_prefix_knob = output_node.knob(knob_name + "_")
        if filename_prefix_knob:
            filename_knob_name = knob_name
            break

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
    data[output_node.name()]["inputs"][filename_knob_name] = new_prefix
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


def extract_meta(data, settings):
    seed = steps = denoise = -1
    lora = lora2 = lora3 = ""

    for name, node in data.items():
        inputs = node["inputs"]

        if seed == -1:
            if "seed" in name.lower():
                seed = inputs.get("value", -1)

        if seed == -1:
            seed = inputs.get("noise_seed", -1)
            seed = seed if type(seed) == int else -1

        if seed == -1:
            seed = inputs.get("seed", -1)
            seed = seed if type(seed) == int else -1

        if steps == -1:
            steps = inputs.get("steps", -1)

        if denoise == -1:
            denoise = inputs.get("denoise", -1)

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

    meta = []

    if not seed == -1:
        meta.append(("seed", seed))

    if not steps == -1:
        meta.append(("steps", steps))

    if not denoise == -1:
        meta.append(("denoise", denoise))

    if lora:
        meta.append(("lora", lora))

    if lora2:
        meta.append(("lora2", lora2))

    if lora3:
        meta.append(("lora3", lora3))

    total_time = settings["pre_inference_time"] + (time() - settings["inference_time"])
    itime = "%02d:%02d" % divmod(int(total_time), 60)
    meta.append(("time", itime))

    return meta


def get_frame_range(data):
    #  Of all the read nodes, it gets the longest range.
    ranges = [n.get("frame_range") for n in data.values() if n.get("frame_range")]
    if not ranges:
        return [1, 1]
    return max(ranges, key=lambda r: r[1] - r[0])


def get_output_path(settings, default_output=False):
    default_output_dir = settings["OUTPUT_DIRECTORY"]

    if default_output:
        return default_output_dir

    collect_dir = settings["COLLECT_DIRECTORY"].strip()
    untitled = settings["project_name"] == "Root"

    if os.path.isabs(collect_dir) and os.path.isdir(collect_dir):
        return collect_dir

    elif collect_dir and not untitled:
        return os.path.join(os.path.dirname(settings["project_name"]), collect_dir)

    return default_output_dir


def relocate_filename(filename, settings):
    if not settings["COLLECT_DIRECTORY"].strip():
        return filename

    if not filename:
        return

    output_dir = get_output_path(settings)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    src_dir = os.path.dirname(filename)
    dst_dir = os.path.join(output_dir, os.path.basename(src_dir))

    if src_dir == dst_dir:
        return filename

    task = nuke.ProgressTask("Relocate from ComfyUI")
    task.setMessage("Relocating: ...")
    task.setProgress(0)

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

    if os.path.exists(src_dir) and not os.listdir(src_dir):
        os.rmdir(src_dir)

    return os.path.join(dst_dir, os.path.basename(filename))


def get_local_filename(settings, default_output=False):
    filename_prefix = settings.get("filename_prefix")

    if not filename_prefix:
        return

    basename = os.path.basename(filename_prefix)
    dirname = os.path.dirname(filename_prefix)

    sequence_output = os.path.join(get_output_path(settings, default_output), dirname)

    if not sequence_output:
        return

    filenames = nuke.getFileNameList(sequence_output)
    if not filenames:
        return

    filename = next((fn for fn in filenames if basename in fn), None)

    if not filename:
        return

    return os.path.join(sequence_output, filename)


def resolve_filename(settings, already_generated=False):
    if already_generated:
        filename = get_local_filename(settings)
    else:
        filename = get_local_filename(settings, default_output=True)
        filename = relocate_filename(filename, settings)

    return filename


def create_empty_read(run_node, data, settings):
    filename = os.path.join(settings["OUTPUT_DIRECTORY"], settings["filename_prefix"])

    filename += "_#####_.png"
    read = create_read(run_node, data, settings, filename)

    if not read:
        return

    first_frame, last_frame = get_frame_range(data)
    read["on_error"].setValue("black")
    read["first"].setValue(1)
    read["last"].setValue(last_frame - first_frame + 1)
    read["origlast"].setValue(last_frame - first_frame + 1)

    return read


def inference_register(run_node, read, filename, metadata):
    register_knob = run_node.knob("register")
    if not register_knob:
        register_knob = nuke.String_Knob("register")
        register_knob.setFlag(nuke.INVISIBLE)
        run_node.addKnob(register_knob)

    register = jsonloads(register_knob.toScript())
    inferences = register.get("inferences", [])

    filenames = [i["filename"] for i in inferences]
    if filename in filenames:
        return

    inferences.append({"filename": filename, "start_frame": read["frame"].value(), "metadata": metadata})

    register["inferences"] = inferences
    register_knob.setValue(jsondumps(register))


def metadata_format(meta):
    if not meta:
        return ""

    label = "<center>"
    for key, value in meta:
        label += '<font color="black" size=1>{}:</font><font color="white" size=1> {}</>\n'.format(key, value)

    return label


def get_register(run_node):
    register_knob = run_node.knob("register")
    if register_knob:
        register = jsonloads(register_knob.toScript())
        return register.get("inferences", [])

    return []


def create_read(run_node, data, settings, filename, already_exists=False):
    if not filename:
        return

    [n.setSelected(False) for n in nuke.selectedNodes()]
    if not already_exists:
        backup_previous_generation(run_node)

    meta = []
    if data and not already_exists:
        meta = extract_meta(data, settings)

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()

    fullname = "{}Read".format(main_node.fullName())
    name = "{}Read".format(main_node.name())
    ext = filename.split(".")[-1].split(" ")[0].lower()

    read = nuke.toNode(fullname)
    if read:
        dx = read.xpos() - main_node.xpos()
        dy = read.ypos() - main_node.ypos()
        dist = math.sqrt(dx**2 + dy**2)

        if dist > 200:
            read.setName(read.name() + "_orphan")
            read = None

    if ext in ["jpg", "exr", "tiff", "png"]:
        if not read:
            read = nuke.createNode("Read", inpanel=False)

        read.knob("file").fromUserText(filename)
        read.knob("frame_mode").setValue("start at")
        read.knob("frame").setValue(str(get_frame_range(data)[0]))
        read.knob("auto_alpha").setValue(True)

        set_correct_colorspace(read)

    elif ext in ["obj"]:
        if not read:
            read = nuke.createNode("ReadGeo", inpanel=False)

        read.knob("file").setValue(filename)
        read.setInput(0, None)

    else:
        return

    read.setName(name)
    read.setXYpos(main_node.xpos(), main_node.ypos() + 35)
    read.knob("tile_color").setValue(main_node.knob("tile_color").value())

    if not settings["DISPLAY_META_IN_READ_NODE"]:
        meta = []

    if not already_exists:
        label = metadata_format(meta)
        read.knob("label").setValue(label)

    comfyui_gizmo = run_node.parent() if run_node.parent().knob("comfyui_gizmo") else run_node

    for i, onode in get_output_nodes(comfyui_gizmo):
        onode.setInput(i, read)

    inference_register(run_node, read, filename, meta)
    return read


def backup_previous_generation(run_node=None):
    if not run_node:
        run_node = nuke.thisNode()

    if not get_register(run_node):
        return

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()

    read = nuke.toNode(main_node.fullName() + "Read")
    if not read:
        return

    is_geo = read.Class() == "ReadGeo"

    if is_geo:
        filename = read.knob("file").value()
    else:
        filename = "{} {}-{}".format(read.knob("file").value(), read.knob("first").value(), read.knob("last").value())

    if is_geo:
        new_read = nuke.createNode("ReadGeo", inpanel=False)
        new_read.knob("file").setValue(filename)
    else:
        new_read = nuke.createNode("Read", inpanel=False)
        new_read.knob("file").fromUserText(filename)
        new_read.knob("frame_mode").setValue(read.knob("frame_mode").value())
        new_read.knob("frame").setValue(read.knob("frame").value())
        new_read.knob("auto_alpha").setValue(True)
        new_read.knob("premultiplied").setValue(read.knob("premultiplied").value())
        set_correct_colorspace(new_read)

    name = f"{main_node.name()}Backup"
    name = normalize_nodename(name)
    new_read.setName(name)
    new_read.knob("label").setValue(read.knob("label").value())

    sort_reads(main_node)


def filename_matching(filename, filenames=[]):
    filename_no_padding = get_name_no_padding(filename, True)
    if any(get_name_no_padding(f, True) == filename_no_padding for f in filenames):
        return True


def get_related_reads(main_node):
    from .execute_runs import get_run

    run_node = get_run(main_node)
    filenames = [f["filename"] for f in get_register(run_node)]

    backup_reads = []
    restore_reads = []

    for n in nuke.allNodes():
        if not n.Class() in ("Read", "ReadGeo"):
            continue

        if not filename_matching(n["file"].value(), filenames):
            continue

        if n.name().startswith(main_node.name() + "Backup"):
            backup_reads.append(n)

        if n.name().startswith(main_node.name() + "Restored"):
            restore_reads.append(n)

    backup_reads.sort(key=lambda n: n["file"].value(), reverse=True)
    restore_reads.sort(key=lambda n: n["file"].value(), reverse=True)

    return backup_reads + restore_reads


def sort_reads(main_node):
    reads = get_related_reads(main_node)
    if not reads:
        return

    xpos = main_node.xpos() + 150
    ypos = main_node.ypos() + 35

    offset_x = 100
    offset_y = 20 + max(reads, key=lambda n: n.screenHeight()).screenHeight()
    per_row = 10

    for i, n in enumerate(reads):
        col = i % per_row
        row = i // per_row
        n.setXYpos(xpos + col * offset_x, ypos + row * offset_y)


def restore_run_generations():
    from .execute_runs import get_run

    node = selected_node()
    if not node:
        return

    run_node = get_run(node)
    register = get_register(run_node)

    if not register:
        show_message("There are no generations before!")
        return

    main_node = get_gizmo_group(run_node)
    if not main_node:
        main_node = run_node

    main_node.parent().begin()
    message = ""
    missing = []

    read = nuke.toNode(main_node.name() + "Read")
    main_filename = read["file"].value() if read else ""

    related_filenames = [n["file"].value() for n in get_related_reads(main_node)]

    for r in register:
        filename = r["filename"]

        dirname = os.path.dirname(filename)
        if not os.path.isdir(dirname) or not os.listdir(dirname):
            missing.append(filename)
            continue

        if filename_matching(filename, [main_filename] + related_filenames):
            continue

        name = f"{main_node.name()}Restored"
        read = nuke.createNode("Read", inpanel=False)
        read.setName(name)

        read.knob("file").fromUserText(filename)
        read.knob("frame_mode").setValue("start at")
        read.knob("frame").setValue(str(r["start_frame"]))
        read.knob("auto_alpha").setValue(True)

        label = metadata_format(r["metadata"])
        read.knob("label").setValue(label)

        set_correct_colorspace(read)

        h, s, l = get_tile_color(main_node)
        if l > 0:
            set_tile_color(read, [h, s / 2, l])

        message += f"{read['file'].value()}\n"

    if not message and not missing:
        show_message("Nothing to restore!")
        return

    sort_reads(main_node)

    if message:
        message = f"<font color=#6cb56b>Restored:</font>\n{message}"

    if missing:
        message += "\n<font color=red>Missing:</font>\n"
        for f in missing:
            fname = f.rsplit(" ", 1)[0]
            message += f"<font color=red>{fname}</font>\n"

    show_message(message)
