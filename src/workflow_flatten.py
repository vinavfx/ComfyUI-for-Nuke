from copy import deepcopy

NOTE_TYPES = ("Note", "MarkdownNote")


def workflow_links(data):
    keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
    return {
        str(link["id"] if isinstance(link, dict) else link[0]): (
            link if isinstance(link, dict) else dict(zip(keys, link))
        )
        for link in data.get("links", [])
    }


def is_socket(host):
    return bool(host) and (not host.get("widget") or host.get("link") is not None)


def instance_values(definition, attrs):
    values = attrs.get("widgets_values") or []
    if isinstance(values, dict):
        return dict(values), []
    proxies = attrs.get("properties", {}).get("proxyWidgets") or []
    if not proxies:
        hosts = {item["name"]: item for item in attrs.get("inputs", [])}
        names = [
            item["name"]
            for item in definition.get("inputs", [])
            if not is_socket(hosts.get(item["name"]))
        ]
        return dict(zip(names, values)), []
    promoted = {}
    overrides = []
    for (node_id, name), value in zip(proxies, values):
        if str(node_id) == "-1":
            promoted[name] = value
        else:
            overrides.append((str(node_id), name, value))
    return promoted, overrides


class WorkflowScope:
    def __init__(self, data, parent=None, instance=None, stack=()):
        self.data = data
        self.parent = parent
        self.instance = instance or {}
        self.stack = stack
        self.prefix = ""
        self.name = None
        self.position = None
        if parent:
            self.prefix = parent.prefix + str(self.instance["id"]) + ":"
            self.name = parent.name or data.get("name")
            self.position = parent.position or self.instance.get("pos")
        self.links = workflow_links(data)
        self.nodes = {str(attrs["id"]): attrs for attrs in data.get("nodes", [])}
        self.input_id = str(data.get("inputNode", {}).get("id", -10))
        self.output_id = str(data.get("outputNode", {}).get("id", -20))
        self.children = {}
        self.promoted, self.overrides = instance_values(data, self.instance)

    def is_top_level(self):
        return self.parent is not None and self.parent.parent is None

    def child(self, attrs, definitions):
        key = str(attrs["id"])
        if key not in self.children:
            if attrs["type"] in self.stack:
                raise ValueError("Recursive subgraph definition")
            self.children[key] = WorkflowScope(
                definitions[attrs["type"]],
                self,
                attrs,
                self.stack + (attrs["type"],),
            )
        return self.children[key]


def resolve_boundary_input(scope, slot, definitions):
    name = scope.data["inputs"][slot]["name"]
    host = next(
        (item for item in scope.instance.get("inputs", []) if item["name"] == name),
        None,
    )
    if host is None or host.get("link") is None:
        return {"scope": scope, "name": name}
    return resolve_source(scope.parent, host["link"], definitions)


def resolve_source(scope, link_id, definitions):
    link = scope.links.get(str(link_id))
    if link is None:
        return None
    origin = str(link["origin_id"])
    slot = link["origin_slot"]
    if scope.parent and origin == scope.input_id:
        return resolve_boundary_input(scope, slot, definitions)
    attrs = scope.nodes.get(origin)
    if attrs is None or attrs["type"] in NOTE_TYPES:
        return None
    if attrs["type"] not in definitions:
        return {
            "origin_id": scope.prefix + origin,
            "origin_slot": slot,
            "type": link.get("type"),
        }
    inner = scope.child(attrs, definitions)
    inner_link = next(
        (
            item
            for item in inner.links.values()
            if str(item["target_id"]) == inner.output_id and item["target_slot"] == slot
        ),
        None,
    )
    if inner_link is None:
        return None
    return resolve_source(inner, inner_link["id"], definitions)


def add_control(flat, key, label, target, widget):
    flat["controls"].setdefault(key, (label, []))[1].append((target, widget))


def promote_widget(flat, source, target, item):
    scope = source["scope"]
    name = source["name"]
    widget = item.get("widget", {}).get("name", item["name"])
    if name in scope.promoted:
        flat["values"].append((target, widget, scope.promoted[name]))
    if scope.is_top_level():
        add_control(flat, (scope.prefix, name), name, target, widget)


def flatten_node(scope, attrs, definitions, flat):
    node = deepcopy(attrs)
    node["id"] = scope.prefix + str(attrs["id"])
    node["pos"] = scope.position or attrs.get("pos", [0, 0])
    flat["names"][node["id"]] = scope.name
    for slot, item in enumerate(node.get("inputs", [])):
        source = resolve_source(scope, item.get("link"), definitions)
        item["link"] = None
        if source is None:
            continue
        if "scope" in source:
            promote_widget(flat, source, node["id"], item)
            continue
        link = dict(
            source, id=len(flat["links"]) + 1, target_id=node["id"], target_slot=slot
        )
        flat["links"].append(link)
        item["link"] = link["id"]
    return node


def flatten_scope(scope, definitions, flat):
    for node_id, widget, value in scope.overrides:
        target = scope.prefix + node_id
        flat["values"].append((target, widget, value))
        if scope.is_top_level():
            add_control(flat, (scope.prefix, node_id, widget), widget, target, widget)
    for attrs in scope.data.get("nodes", []):
        if attrs["type"] in NOTE_TYPES:
            continue
        if attrs["type"] in definitions:
            flatten_scope(scope.child(attrs, definitions), definitions, flat)
        else:
            flat["nodes"].append(flatten_node(scope, attrs, definitions, flat))


def flatten_workflow(data, definitions):
    flat = {
        "nodes": [],
        "links": [],
        "groups": data.get("groups", []),
        "values": [],
        "controls": {},
        "names": {},
    }
    flatten_scope(WorkflowScope(data), definitions, flat)
    return flat


def node_parents(flat):
    parents = {attrs["id"]: [] for attrs in flat["nodes"]}
    for link in flat["links"]:
        parents[link["target_id"]].append(link)
    setters = {
        attrs.get("title"): attrs["id"]
        for attrs in flat["nodes"]
        if attrs["type"] == "easy setNode"
    }
    for attrs in flat["nodes"]:
        title = attrs.get("title")
        if attrs["type"] == "easy getNode" and title in setters:
            parents[attrs["id"]].append({"origin_id": setters[title], "type": None})
    return parents


def upstream_ids(parents, root):
    seen = set()
    pending = [root]
    while pending:
        node_id = pending.pop()
        if node_id not in seen:
            seen.add(node_id)
            pending.extend(link["origin_id"] for link in parents.get(node_id, []))
    return seen


def main_output_id(flat, parents, is_output):
    origins = {link["origin_id"] for links in parents.values() for link in links}
    outputs = [attrs for attrs in flat["nodes"] if is_output(attrs["id"])]
    sinks = [attrs for attrs in flat["nodes"] if attrs["id"] not in origins]

    def weight(attrs):
        active = attrs.get("mode", 0) == 0
        return active, len(upstream_ids(parents, attrs["id"]))

    main = max(outputs or sinks, key=weight, default=None)
    return main["id"] if main else None


def image_source(parents, output_id):
    seen = set()
    pending = [output_id]
    while pending:
        node_id = pending.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        for link in parents.get(node_id, []):
            if link.get("type") == "IMAGE":
                return link
            pending.append(link["origin_id"])
    return None


def replaced_ids(parents, output_id, origin_id):
    return [
        node_id
        for node_id in upstream_ids(parents, output_id)
        if node_id != origin_id and origin_id in upstream_ids(parents, node_id)
    ]
