"""Named, editable MediaWiki views and their explicit publication dependencies."""

import html
import re

from wiki_data import DataError
from wiki_display import INERT


VIEW_SELECTOR = "{{{view|<noinclude>page</noinclude>}}}"


def scroll_open(label="Table", css_class="mirklurk-scroll"):
    return (
        '<div class="' + html.escape(css_class, quote=True) + '" role="group" tabindex="0" aria-label="'
        + html.escape(label + " (scroll horizontally)", quote=True)
        + '" style="max-width:100%;overflow-x:auto;">\n'
    )


def selective_view(content, view, default=False):
    cases = ["page", view]
    if default:
        cases.append("")
    return (
        "<onlyinclude>{{#switch:" + VIEW_SELECTOR + "|" + "|".join(cases)
        + "=" + content + "|#default=}}</onlyinclude>"
    )


def filtered_row(content, parameter, values):
    return (
        "{{#switch:{{{" + parameter + "|}}}||" + "|".join(sorted(set(values)))
        + "=" + content + "|#default=}}"
    )


def html_row(cells, normal_only=()):
    return "<tr>" + "".join(
        ("<noinclude>" if index in normal_only else "") + "<td>" + cell + "</td>"
        + ("</noinclude>" if index in normal_only else "")
        for index, cell in enumerate(cells)
    ) + "</tr>\n"


def html_table(headers, rows, normal_only=()):
    return (
        scroll_open() + '<table class="wikitable">\n<tr>'
        + "".join(
            ("<noinclude>" if index in normal_only else "") + '<th scope="col">' + heading + "</th>"
            + ("</noinclude>" if index in normal_only else "")
            for index, heading in enumerate(headers)
        )
        + "</tr>\n" + "".join(rows) + "</table>\n</div>\n"
    )


def transclusions(text):
    references = set()
    for match in re.finditer(r"\{\{:([^{}\n]+)\}\}", INERT.sub("", text)):
        owner, *arguments = match.group(1).split("|")
        parameters = {}
        for argument in arguments:
            key, separator, value = argument.partition("=")
            if not separator or not key.strip() or key.strip() in parameters:
                raise DataError("selective transclusion requires unique named parameters")
            parameters[key.strip()] = value.strip()
        references.add((owner.strip(), tuple(sorted(parameters.items()))))
    return sorted(references)


def available_views(text):
    blocks = re.findall(r"<onlyinclude>(.*?)</onlyinclude>", text, re.DOTALL)
    if not blocks or len(blocks) != text.count("<onlyinclude>") or len(blocks) != text.count("</onlyinclude>"):
        return set()
    views = set()
    prefix = "{{#switch:" + VIEW_SELECTOR + "|"
    for block in blocks:
        if block.startswith(prefix):
            cases, separator, _ = block[len(prefix):].partition("=")
            if not separator or not block.endswith("|#default=}}"):
                return set()
            views.update(case for case in cases.split("|") if case != "page")
        elif len(blocks) == 1:
            views.add("")
        else:
            return set()
    return views


def validate_transclusions(pages):
    for title, text in pages.items():
        for owner, arguments in transclusions(text):
            if owner not in pages:
                raise DataError(f"{title}: transclusion owner {owner} is missing")
            view = dict(arguments).get("view", "")
            if view not in available_views(pages[owner]):
                raise DataError(f"{title}: {owner} does not expose the requested selective view")
