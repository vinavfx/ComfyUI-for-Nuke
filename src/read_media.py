# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import os
import math
import re

import nuke  # type: ignore
from time import time

from ..nuke_util.media_util import get_name_no_padding
from ..nuke_util.nuke_util import (
    get_output_nodes,
    selected_node,
    set_tile_color,
    get_tile_color,
)
from .nodes import get_input
from .common import get_date_code, jsonloads, jsondumps, show_message
from .update_menu import normalize_nodename


def prepare_output_path(run_node, settings, update=True, data=None):
    output_node = get_input(run_node, 0)
    if not output_node:
        return

    settings.pop("output_filepath", None)
    settings.pop("filename_prefix", None)
    settings.pop("output_format", None)
    output_data = (data or {}).get(output_node.name(), {})
    inputs = output_data.get("inputs", {})
    format_knob = output_node.knob("format_")
    settings["output_format"] = inputs.get(
        "format", format_knob.value() if format_knob else "png"
    )

    for knob_name in ("filepath", "file_path"):
        filepath_knob = output_node.knob(knob_name + "_")
        if filepath_knob:
            filepath = inputs.get(knob_name, filepath_knob.value())
            settings["output_filepath"] = filepath
            return filepath

    filename_prefix_knob = output_node.knob("filename_prefix_")

    if not filename_prefix_knob:
        return

    if not update:
        settings["filename_prefix"] = filename_prefix_knob.value()
        return settings["filename_prefix"]

    prefix = filename_prefix_knob.value()
    old_rand = prefix.split("/")[0]

    if old_rand.isdigit():
        prefix = prefix.replace(old_rand + "/", "")

    new_prefix = "{}/{}".format(get_date_code(), prefix)
    filename_prefix_knob.setValue(new_prefix)
    if data is not None:
        data[output_node.name()]["inputs"]["filename_prefix"] = new_prefix
    settings["filename_prefix"] = new_prefix
    return new_prefix


def set_correct_colorspace(read):
    filename = read.knob("file").value()
    ext = filename.split(".")[-1].lower()

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
    seed = denoise = -1
    lora = lora2 = ""

    for name, node in data.items():
        inputs = node["inputs"]

        if seed == -1:
            if "seed" in name.lower():
                seed = inputs.get("value", -1)

        if seed == -1:
            seed = inputs.get("noise_seed", -1)
            seed = seed if type(seed) is int else -1

        if seed == -1:
            seed = inputs.get("seed", -1)
            seed = seed if type(seed) is int else -1

        if denoise == -1:
            denoise = inputs.get("denoise", -1)

        if name in ("lora1_model", "lora2_model"):
            lora_name = inputs.get("lora_name", "").split("/")[-1].rsplit(".", 1)[0]
            lora_strength = inputs.get("strength_model", 0)
            formatted = "{}:{}".format(lora_name, lora_strength)

            if name == "lora1_model":
                lora = formatted
            elif name == "lora2_model":
                lora2 = formatted

    meta = []

    if not seed == -1:
        meta.append(("seed", seed))

    if not denoise == -1:
        meta.append(("denoise", denoise))

    if lora:
        meta.append(("lora", lora))

    if lora2:
        meta.append(("lora2", lora2))

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


def get_inference_pattern(settings):
    extension = settings.get("output_format", "png")
    filepath = settings.get("output_filepath")
    if filepath:
        filepath = os.path.abspath(os.path.expanduser(filepath.strip().strip('"')))
        stem, suffix = os.path.splitext(filepath)
        if suffix.lower() not in (".png", ".exr"):
            stem = filepath
        basename = re.sub(
            r"%0?(\d*)d",
            lambda match: "#" * max(1, int(match[1] or 1)),
            os.path.basename(stem),
        )
        stem = os.path.join(os.path.dirname(stem), basename)
        if "#" not in basename:
            stem += "_####"
        return f"{stem}.{extension}"

    prefix = settings.get("filename_prefix")
    if prefix:
        filename = os.path.join(settings["OUTPUT_DIRECTORY"], prefix)
        return f"{filename}_#####_.{extension}"


def find_inference_file(settings):
    pattern = get_inference_pattern(settings)
    if not pattern:
        return

    sequence_output = os.path.dirname(pattern)
    if not os.path.isdir(sequence_output):
        return

    filenames = nuke.getFileNameList(sequence_output) or []
    if settings.get("output_filepath"):
        expression = re.escape(os.path.basename(pattern))
        expression = re.sub(r"(?:\\#)+", lambda match: r"[0-9#]+", expression)
        expression += r"(?: -?\d+--?\d+)?"
        filename = next(
            (
                name
                for name in filenames
                if re.fullmatch(
                    expression,
                    re.sub(r"%0?\d*d", "####", name),
                )
            ),
            None,
        )
    else:
        basename = os.path.basename(settings["filename_prefix"])
        filename = next((name for name in filenames if basename in name), None)

    if filename:
        return os.path.join(sequence_output, filename)


def register_temporary_inference(run_node, data, settings):
    first_frame, last_frame = get_frame_range(data)
    frame_count = last_frame - first_frame + 1
    filename = "{} 1-{}".format(get_inference_pattern(settings), frame_count)
    settings["temporary_inference_filename"] = filename
    inference_register(
        run_node,
        None,
        filename,
        [],
        start_frame=first_frame,
    )


def create_empty_read(run_node, data, settings):
    filename = get_inference_pattern(settings)
    read = create_read(run_node, data, settings, filename)

    if not read:
        return

    first_frame, last_frame = get_frame_range(data)
    read["on_error"].setValue("black")
    read["first"].setValue(1)
    read["last"].setValue(last_frame - first_frame + 1)
    read["origlast"].setValue(last_frame - first_frame + 1)

    return read


def inference_register(
    run_node,
    read,
    filename,
    metadata,
    temporary_filename=None,
    start_frame=1,
):
    register_knob = run_node.knob("register")
    if not register_knob:
        register_knob = nuke.String_Knob("register")
        register_knob.setFlag(nuke.INVISIBLE)
        run_node.addKnob(register_knob)

    register = jsonloads(register_knob.toScript())
    inferences = register.get("inferences", [])

    filenames = [i["filename"] for i in inferences]

    if read:
        frame_knob = read.knob("frame")
        start_frame = frame_knob.value() if frame_knob else 1

    inference = {
        "filename": filename,
        "start_frame": start_frame,
        "metadata": metadata,
    }
    if temporary_filename in filenames:
        temporary_index = filenames.index(temporary_filename)
        if filename in filenames:
            filename_index = filenames.index(filename)
            inferences[filename_index] = inference
            if temporary_index != filename_index:
                inferences.pop(temporary_index)
        else:
            inferences[temporary_index] = inference
    elif filename not in filenames:
        inferences.append(inference)
    else:
        return

    register["inferences"] = inferences
    register_knob.setValue(jsondumps(register))


def inference_unregister(run_node, settings):
    register_knob = run_node.knob("register")
    filename = settings.get("temporary_inference_filename")
    if not register_knob or not filename:
        return

    register = jsonloads(register_knob.toScript())
    register["inferences"] = [
        inference
        for inference in register.get("inferences", [])
        if inference["filename"] != filename
    ]
    register_knob.setValue(jsondumps(register))


def metadata_format(meta):
    if not meta:
        return ""

    label = "<center>"
    for key, value in meta:
        label_format = (
            '<font color="black" size=1>{}:</font><font color="white" size=1> {}</>\n'
        )
        label += label_format.format(key, value)

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
        meta = list(settings.get("custom_metadata", {}).items())
        meta.extend(extract_meta(data, settings))

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

    comfyui_gizmo = (
        run_node.parent() if run_node.parent().knob("comfyui_gizmo") else run_node
    )

    if comfyui_gizmo.knob("comfyui_gizmo") is not None:
        source = read.knobs().get("comfyui_source")
        if source is not None or settings.get("LINK_DEPENDENCY_SOURCE", False):
            if source is None:
                source = nuke.Link_Knob("comfyui_source")
                source.setFlag(nuke.INVISIBLE)
                read.addKnob(source)
            source.makeLink(comfyui_gizmo.fullName(), "comfyui_gizmo")

    for i, onode in get_output_nodes(comfyui_gizmo):
        onode.setInput(i, read)

    inference_register(
        run_node,
        read,
        filename,
        meta,
        temporary_filename=settings.get("temporary_inference_filename"),
    )
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
        filename = "{} {}-{}".format(
            read.knob("file").value(),
            read.knob("first").value(),
            read.knob("last").value(),
        )

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

        hue, saturation, lightness = get_tile_color(main_node)
        if lightness > 0:
            set_tile_color(read, [hue, saturation / 2, lightness])

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
