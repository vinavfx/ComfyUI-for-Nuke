import nuke  # type: ignore


def unlink_dependencies():
    selected = nuke.selectedNodes()
    if not selected:
        nuke.message("Select Read nodes or ComfyUI gizmos to unlink dependencies.")
        return

    gizmos = {
        node.fullName() for node in selected if node.knob("comfyui_gizmo") is not None
    }
    unlinked = 0
    with nuke.Undo():
        for node in nuke.allNodes(recurseGroups=True):
            source = node.knobs().get("comfyui_source")
            if source is None:
                continue
            linked = source.getLinkedKnob()
            matches_gizmo = (
                linked is not None
                and linked.name() == "comfyui_gizmo"
                and linked.node().fullName() in gizmos
            )
            if node in selected or matches_gizmo:
                node.removeKnob(source)
                unlinked += 1

    nuke.message("Removed {} dependency source links.".format(unlinked))
