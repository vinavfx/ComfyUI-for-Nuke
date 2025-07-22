# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import nuke  # type: ignore
import re
from ..python_util.util import fwrite
import os


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


def status_diff(a, b):
    if not a or not b:
        return

    tokens_a = re.findall(r'\S+', a)
    tokens_b = re.findall(r'\S+', b)

    diffs = [(x, y) for x, y in zip(tokens_a, tokens_b) if x != y]
    diff = ''

    for x, y in diffs:
        diff += '{} -> {}\n'.format(x, y)

    info = 'diff:\n{}\n\nPREVIOUS:\n{}\n\nCURRENT:\n{}'.format(diff, a, b)
    file = '/tmp/comfyu2nuke_diff.txt'
    fwrite(file, info)
    if nuke.ask('diff -> {}, open?'.format(file)):
        os.system('pluma {}'.format(file))
