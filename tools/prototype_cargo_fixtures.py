"""Synthetic records only; these pages are never part of the published corpus."""

import json


TEMPLATE = "Template:Prototype record"
MODULE = "Module:Prototype record"
OWNER = "Prototype item"
NEW_OWNER = "New prototype item"
MOVED = "Renamed prototype item"
FIELDS = {
    "variant": ("Variant", "string"), "product": ("Product", "wiki-page-name"),
    "quantity": ("Output quantity", "string"), "ap": ("AP", "number"),
    "ingredients": ("Ingredients and quantities", "string"),
    "stations": ("Stations", "string"), "merchants": ("Merchants", "string"),
    "condition": ("Condition", "string"),
}
SCHEMA = ("Variant=String|Product=Page|Quantity=String|AP=Float|Ingredients=List (;) of Page"
          "|Inputs=Text|Stations=List (;) of Page|Merchants=List (;) of Page|Requirement=Text")

LUA = r'''
local p = {}
function p.main(frame)
    local parent = frame:getParent()
    local a = parent.args
    local names, inputs = {}, {}
    for line in mw.text.gsplit(a.ingredients or '', '\n', true) do
        if mw.text.trim(line) ~= '' then
            local name, quantity = line:match('^%s*(.-)%s*=%s*([0-9]+)%s*$')
            if not name or name == '' or tonumber(quantity) <= 0 then
                error('Ingredients require one Item = positive quantity per line.')
            end
            table.insert(names, name)
            table.insert(inputs, name .. ' = ' .. quantity)
        end
    end
    local current = mw.title.getCurrentTitle()
    local caller = parent:getParent()
    -- Reuse renders the record, but only the page containing the direct call owns it.
    if current.namespace == 0 and caller and caller:getTitle() == current.prefixedText then
        mw.ext.cargo.store('PrototypeRecords', {
            Variant=a.variant, Product=a.product, Quantity=a.quantity, AP=a.ap,
            Ingredients=table.concat(names, ';'), Inputs=table.concat(inputs, '\n'),
            Stations=a.stations, Merchants=a.merchants, Requirement=a.condition
        })
    end
    local out = mw.html.create('div'):addClass('prototype-record')
    out:tag('strong'):wikitext(a.product or ''):done()
    out:tag('p'):text('Variant: ' .. (a.variant or '') .. '; AP ' .. (a.ap or '')):done()
    out:tag('p'):text(table.concat(inputs, '; ')):done()
    out:tag('p'):text('Stations: ' .. (a.stations or '') .. '; Merchants: ' .. (a.merchants or '')):done()
    out:tag('p'):text(a.condition or ''):done()
    return tostring(out)
end
return p
'''


def record(variant="base", ap="2", stations="Prototype bench;Prototype camp", product="Synthetic salve"):
    values = {
        "variant": variant, "product": product, "quantity": "1", "ap": ap,
        "ingredients": "Synthetic fiber = 4\nSynthetic resin = 2\nSynthetic water = 1\n"
                       "Synthetic salt = 1\nSynthetic leaf = 3",
        "stations": stations, "merchants": "Prototype trader",
        "condition": "Only while the synthetic quest is active.",
    }
    return "{{Prototype record|" + "|".join(f"{k}={v}" for k, v in values.items()) + "}}"


def query(where):
    return ("{{#cargo_query:tables=PrototypeRecords|fields=_pageName=Owner,Variant,Product,AP,Inputs,Requirement"
            "|where=" + where + "|order by=_pageName,Variant|format=template|template=Prototype result|named args=yes"
            "|default=No matching records.}}")


READERS = {
    "Prototype bench": "Stations HOLDS 'Prototype bench'",
    "Prototype new station": "Stations HOLDS 'Prototype new station'",
    "Synthetic resin": "Ingredients HOLDS 'Synthetic resin'",
    "Prototype trader": "Merchants HOLDS 'Prototype trader'",
}


def pages():
    metadata = {
        "description": "Synthetic author-owned record. Ingredients: one Item = quantity per line. "
                       "Stations and merchants: semicolon-separated page names.",
        "format": "inline", "paramOrder": list(FIELDS),
        "params": {key: {"label": label, "type": kind, "required": True}
                   for key, (label, kind) in FIELDS.items()},
    }
    return {
        MODULE: LUA,
        TEMPLATE: "<includeonly>{{#invoke:Prototype record|main}}</includeonly>"
                  "<noinclude>{{#cargo_declare:_table=PrototypeRecords|" + SCHEMA + "}}"
                  "<templatedata>" + json.dumps(metadata) + "</templatedata></noinclude>",
        "Template:Prototype result": '<includeonly><div class="prototype-result">'
                  '[[{{{Owner}}}|{{{Owner}}}]] - {{{Variant}}}: {{{Product}}}; AP {{{AP}}}; '
                  '{{{Inputs}}}; {{{Requirement}}} '
                  '[{{fullurl:{{{Owner}}}|veaction=edit}} Edit data]</div></includeonly>',
    }
