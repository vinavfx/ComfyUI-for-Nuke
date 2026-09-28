from urllib.parse import quote

import nuke  # type: ignore

from .common import get_settings, show_message
from .connection import GET


def local_templates(categories):
    templates = {}
    for category in categories:
        if category.get("moduleName") != "default":
            continue
        for template in category.get("templates", []):
            if template.get("openSource") is False:
                continue
            name = template.get("name")
            if name:
                templates[name] = template
    return sorted(
        templates.values(),
        key=lambda template: template.get("title", template["name"]).casefold(),
    )


def select_template():
    settings = get_settings()
    categories = GET("templates/index.json", settings, timeout=10)
    if not isinstance(categories, list):
        show_message("The configured ComfyUI server did not return a template catalog.")
        return
    templates = local_templates(categories)
    if not templates:
        show_message("No local ComfyUI templates are available on this server.")
        return
    search = nuke.getInput("Search ComfyUI templates (leave empty to show all)", "")
    if search is None:
        return
    words = search.casefold().split()
    templates = [
        template
        for template in templates
        if all(word in str(template).casefold() for word in words)
    ]
    if not templates:
        show_message("No ComfyUI templates match your search.")
        return
    labels = [
        "{}: {}".format(index, template.get("title", template["name"]))
        for index, template in enumerate(templates, 1)
    ]
    panel = nuke.Panel("Import ComfyUI Template")
    panel.setWidth(650)
    choices = " ".join(label.replace(" ", "\\ ") for label in labels)
    panel.addEnumerationPulldown("Template", choices)
    if not panel.show():
        return
    template = templates[labels.index(panel.value("Template"))]
    endpoint = "templates/{}.json".format(quote(template["name"], safe=""))
    return GET(endpoint, settings, timeout=10)
