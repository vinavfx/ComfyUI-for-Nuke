from .nodes import get_node_data

updating_nodes = set()


def get_nuke_metadata(ordered_inputs):
    metadata = {}
    for key, input_value, _, _ in ordered_inputs:
        input_class = input_value[0]
        info = input_value[1] if len(input_value) == 2 else {}
        if not isinstance(info, dict) or info.get("forceInput", False):
            continue
        is_knob = isinstance(input_class, list) or input_class in (
            "INT",
            "FLOAT",
            "STRING",
            "BOOLEAN",
            "COMBO",
        )
        rules = info.get("nuke")
        if is_knob and isinstance(rules, dict) and rules:
            metadata[key] = rules
    return metadata


def conditions_match(knobs, conditions):
    return all(
        name in knobs and knobs[name].value() in values
        for name, values in conditions.items()
    )


def apply_nuke_metadata(node):
    node_name = node.fullName()
    if node_name in updating_nodes:
        return
    data = get_node_data(node)
    metadata = data.get("nuke_metadata", {})
    if not metadata:
        return

    names = data.get("knobs_input_names", {})
    knobs = {
        names.get(name, name[:-1]): node.knob(name)
        for name in data.get("knobs_order", [])
        if node.knob(name) is not None
    }
    updating_nodes.add(node_name)
    try:
        for name, rules in metadata.items():
            knob = knobs.get(name)
            if knob is None:
                continue
            for rule, setter in (
                ("visible_when", knob.setVisible),
                ("enabled_when", knob.setEnabled),
            ):
                if rule in rules:
                    setter(conditions_match(knobs, rules[rule]))

            options_when = rules.get("options_when", {})
            if not options_when or not hasattr(knob, "setValues"):
                continue
            options = data.get("nuke_options", {}).get(name, [])
            for selector, choices in options_when.items():
                source = knobs.get(selector)
                if source is not None:
                    options = choices.get(str(source.value()), options)
            options = [str(value) for value in options]
            if not options or knob.values() == options:
                continue
            value = knob.value()
            knob.setValues(options)
            knob.setValue(value if value in options else options[0])
    finally:
        updating_nodes.remove(node_name)
