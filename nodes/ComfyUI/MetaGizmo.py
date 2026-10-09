import nuke

from ...nuke_util.nuke_util import get_output_nodes
from ...src.cmd import dependency_gizmos, run_dependencies
from ...src.execute_runs import prepare_multiversions


def publish_read(meta, source, output, index):
    parent = meta.parent()
    name = meta.name() + "Read"
    if index:
        name = meta.name() + output.name() + "Read"
    xpos = meta.xpos() + index * 150
    ypos = meta.ypos() + 35
    with parent:
        read = next((node for node in parent.nodes() if node.name() == name), None)
        if read is not None:
            distance = abs(read.xpos() - xpos) + abs(read.ypos() - ypos)
            if read.Class() != source.Class() or distance > 200:
                read.setName(name + "_orphan")
                read = None
        if read is None:
            for node in nuke.selectedNodes():
                node.setSelected(False)
            read = nuke.createNode(source.Class(), inpanel=False)
        for knob_name in (
            "file",
            "first",
            "last",
            "origfirst",
            "origlast",
            "frame_mode",
            "frame",
            "colorspace",
            "raw",
            "auto_alpha",
            "premultiplied",
            "label",
        ):
            source_knob = source.knob(knob_name)
            target_knob = read.knob(knob_name)
            if source_knob is not None and target_knob is not None:
                target_knob.fromScript(source_knob.toScript())
        read.setName(name)
        read.setXYpos(xpos, ypos)
        read["tile_color"].setValue(meta["tile_color"].value())
        if index == 0:
            for input_index, node in get_output_nodes(meta):
                node.setInput(input_index, read)
    return read


def run(meta=None, settings=None):
    if meta is None:
        meta = nuke.thisNode()
    outputs = [
        node
        for node in meta.nodes()
        if node.Class() == "NoOp"
        and node.knob("comfyui_meta_output") is not None
        and node.input(0) is not None
    ]
    outputs.sort(key=lambda node: (node.ypos(), node.xpos(), node.name()))
    group_output = next(
        (node for node in meta.nodes() if node.Class() == "Output"), None
    )
    primary = group_output.input(0) if group_output is not None else None
    if primary in outputs:
        outputs.remove(primary)
        outputs.insert(0, primary)
    if not outputs:
        nuke.message("Connect at least one green MetaOutput to a ComfyUI gizmo.")
        return

    gizmos = []
    targets = []
    try:
        for output in outputs:
            dependencies = dependency_gizmos(output)
            if not dependencies:
                nuke.message(
                    "No ComfyUI gizmos are connected to {}.".format(output.name())
                )
                return
            targets.append(dependencies[-1])
            for gizmo in dependencies:
                if gizmo not in gizmos:
                    gizmos.append(gizmo)
    except ValueError as error:
        nuke.message(str(error))
        return
    def execution_finished():
        for index, (output, target) in enumerate(zip(outputs, targets)):
            source = next(
                (
                    node
                    for node in target.parent().nodes()
                    if node.name() == target.name() + "Read"
                ),
                None,
            )
            if source is None:
                nuke.message(
                    "{} did not produce a Read node.".format(target.fullName())
                )
                return
            publish_read(meta, source, output, index)

    runs = []
    for gizmo in gizmos:
        if gizmo in targets:
            runs.extend(prepare_multiversions(gizmo))
        else:
            runs.append(gizmo)
    run_dependencies(
        runs, execution_finished, settings=settings, dependency_nodes=gizmos
    )
