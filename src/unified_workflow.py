import nuke  # type: ignore

from .nodes import extract_data, get_input


def unified_gizmos(gizmo):
    from .cmd import dependency_gizmos

    gizmos = dependency_gizmos(gizmo)
    for target in gizmos:
        for index in range(target.inputs()):
            source = target.input(index)
            if source is None or source.knob("comfyui_gizmo") is not None:
                continue
            if dependency_gizmos(source):
                raise ValueError(
                    "Unified submissions do not allow intermediate Nuke nodes "
                    "between ComfyUI gizmos: {}".format(source.fullName())
                )
    return gizmos


def extract_unified_data(run_node, settings):
    try:
        gizmos = unified_gizmos(run_node.parent())
        data = {}
        outputs = {}
        changed = False
        for gizmo in gizmos:
            input_links = {}
            for child in gizmo.nodes():
                if child.Class() != "Input":
                    continue
                source = gizmo.input(int(child["number"].value()))
                if source is not None and source.fullName() in outputs:
                    input_links[child.fullName()] = outputs[source.fullName()]
            current_run = gizmo.node("Run")
            with current_run:
                current_data, input_changed, error = extract_data(
                    current_run, settings, input_links
                )
            if not current_data:
                return {}, None, error
            changed = changed or input_changed
            output_node = get_input(current_run, 0)
            if output_node is None:
                raise ValueError(
                    "Run is not connected: {}".format(current_run.fullName())
                )
            output_name = output_node.name()
            prefix = "" if gizmo == run_node.parent() else gizmo.fullName() + "."
            names = {name: prefix + name for name in current_data}
            for node_data in current_data.values():
                for value in node_data["inputs"].values():
                    if isinstance(value, list) and len(value) == 2:
                        if isinstance(value[0], str) and value[0] in names:
                            value[0] = names[value[0]]
            if gizmo != run_node.parent():
                output_data = current_data.pop(output_name)
                if output_data["class_type"] != "WriteImage":
                    raise ValueError(
                        "Unified dependencies must end with WriteImage: {}".format(
                            gizmo.fullName()
                        )
                    )
                image = output_data["inputs"].get("images")
                if not isinstance(image, list) or len(image) != 2:
                    raise ValueError(
                        "WriteImage has no connected image: {}".format(gizmo.fullName())
                    )
                outputs[gizmo.fullName()] = image
            data.update({names[name]: value for name, value in current_data.items()})
        return data, changed, ""
    except ValueError as error:
        message = str(error)
        nuke.message(message)
        return {}, None, message
