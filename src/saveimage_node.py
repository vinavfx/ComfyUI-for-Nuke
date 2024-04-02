# -----------------------------------------------------------
# AUTHOR --------> Francisco Jose Contreras Cuevas
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import shutil
import os
import nuke  # type: ignore

from ..python_util.util import recursive_rename
from ..nuke_util.nuke_util import duplicate_node
from .common import get_available_name


def save_image_backup():
    nuke.thisKnob().setEnabled(False)
    this = nuke.thisNode()
    read = nuke.toNode('read')
    filename = read.knob('file').value()
    secdir = os.path.dirname(filename)
    output_dir = os.path.dirname(secdir)

    if not os.path.isdir(secdir):
        return

    basename = os.path.basename(secdir)
    backup_prefix = '{}_backup'.format(basename)
    backup_name = get_available_name(backup_prefix, output_dir)
    backup_dir = os.path.join(output_dir, backup_name)

    number = backup_name.split('_')[-1]

    new_filename = '{}/{}/{}_#####_.png'.format(
        output_dir, backup_name, backup_name)

    shutil.copytree(secdir, backup_dir)
    recursive_rename(backup_dir, basename, backup_name)

    if not '.nk' in this.parent().name():
        this = this.parent()

    new_read = duplicate_node(read, parent=this.parent())
    new_read.knob('file').setValue(new_filename)
    new_read.setName(this.name() + '_backup_' + number)
    new_read.knob('reload').execute()

    backup_nodes = []
    this.parent().begin()

    for n in nuke.allNodes():
        if not this.name() + '_' in n.name():
            continue

        num = int(n.name().split('_')[-1])
        backup_nodes.append((num, n))

    backup_nodes = sorted(backup_nodes, key=lambda x: x[0])

    xpos = this.xpos()
    for num, n in reversed(backup_nodes):
        xpos += 150
        n.setXYpos(xpos, this.ypos())
