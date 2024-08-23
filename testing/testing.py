# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore


def create_all_comfyui_nodes():
    def get_menu_items(menu, items=None):
        if items is None:
            items = []

        for item in menu.items():
            if isinstance(item, nuke.Menu):
                get_menu_items(item, items)
            else:
                items.append(item)

        return items

    menu = nuke.menu('Nodes').menu('ComfyUI')
    all_items = get_menu_items(menu)

    for item in all_items:
        if 'Update all' in item.name():
            continue

        item.invoke()
