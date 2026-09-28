local p = {}

local function failure(message)
    return tostring(mw.html.create('strong'):addClass('error mirklurk-display-error')
        :attr('role', 'alert'):wikitext('Display error: ' .. message))
end

local function argument(frame)
    local value = frame.args[1] or ''
    if #value > 16384 then
        return nil
    end
    return mw.text.trim(value)
end

local function assets()
    return mw.loadData('Module:Display assets')
end

function p.creature(frame)
    local value = argument(frame)
    if not value or #value > 160 then
        return failure('Creature requires a registered creature page title (at most 160 bytes).')
    end
    local title = mw.title.new(value)
    if not title or title.namespace ~= 0 or title.isExternal or title.fragment ~= '' then
        return failure('Creature requires a main-namespace creature page title without a section fragment.')
    end
    local markup = assets().creatures[title.text]
    if not markup then
        return failure('Unknown creature title. Use a registered creature page title; NPCs are not creatures.')
    end
    return tostring(mw.html.create('span'):addClass('mirklurk-creature')
        :attr('title', title.text):attr('aria-label', title.text):wikitext(frame:preprocess(markup)))
end

function p.coins(frame)
    local value = argument(frame)
    if not value or #value < 1 or #value > 18 or not value:match('^[0-9]+$') then
        return failure('Coins requires 1 to 18 digits, an integer total copper from 0 to 999999999999999999.')
    end
    -- Split decimal strings, never convert the potentially large gold count to a float.
    value = value:gsub('^0+', '')
    local padded = string.rep('0', math.max(0, 4 - #value)) .. value
    local gold = padded:sub(1, -4):gsub('^0+', '')
    local silver = tonumber(padded:sub(-3, -3))
    local copper = tonumber(padded:sub(-2))
    local icons = assets().coins
    local parts = {}
    local function add(count, name)
        parts[#parts + 1] = frame:preprocess(icons[name]) .. ' ' .. count .. ' ' .. name
    end
    if gold ~= '' then add(gold, 'gold') end
    if silver > 0 then add(tostring(silver), 'silver') end
    if copper > 0 or #parts == 0 then add(tostring(copper), 'copper') end
    return table.concat(parts, ' ')
end

local function split(value, separator)
    local result, start = {}, 1
    while true do
        local boundary = value:find(separator, start, true)
        result[#result + 1] = value:sub(start, boundary and boundary - 1 or #value)
        if not boundary then return result end
        start = boundary + 1
    end
end

local function grid(frame, health)
    local value = argument(frame)
    if not value or value == '' then
        return failure('A grid requires nonempty comma-separated cells and semicolon-separated rows (at most 16384 bytes).')
    end
    local label = health and 'Base health' or mw.text.trim(frame.args.label or 'Attack pattern')
    if not health and label ~= 'Attack pattern' and label ~= 'Melee attack' and label ~= 'Ranged attack' then
        return failure('Attack grid label must be Attack pattern, Melee attack or Ranged attack.')
    end
    local rows = split(value, ';')
    if #rows > 32 then return failure('A grid allows at most 32 rows and 32 columns.') end
    local width, occupied, totalLow, totalHigh = nil, 0, 0, 0
    for y, row in ipairs(rows) do
        rows[y] = split(row, ',')
        width = width or #rows[y]
        if width > 32 or #rows[y] ~= width then
            return failure('A grid must be rectangular, with at most 32 rows and 32 columns.')
        end
        for x, raw in ipairs(rows[y]) do
            local cell = mw.text.trim(raw)
            if cell == '0' then
                rows[y][x] = false
            elseif health then
                if not cell:match('^[1-4]$') then
                    return failure('Health cells must be 0 (hole), 1 (one HP), or 2, 3, 4 (one HP with armor).')
                end
                rows[y][x] = { armor = tonumber(cell) - 1 }
                occupied = occupied + 1
            else
                local low, high = cell:match('^([0-9]+)%-([0-9]+)$')
                if not low and cell:match('^[0-9]+$') then low, high = cell, cell end
                if not low or #low > 4 or #high > 4 then
                    return failure('Attack cells must be 0 (gap), positive integers, or ordered hyphen ranges from 0 to 1000.')
                end
                low, high = tonumber(low), tonumber(high)
                if low > high or high < 1 or high > 1000 then
                    return failure('Attack ranges require 0 <= lower <= upper <= 1000 and a positive upper endpoint.')
                end
                rows[y][x] = { low = low, high = high }
                occupied, totalLow, totalHigh = occupied + 1, totalLow + low, totalHigh + high
            end
        end
    end
    if health and occupied == 0 then return failure('A health grid needs at least one occupied cell.') end
    local wrapper = mw.html.create('div'):css('overflow-x', 'auto')
    local gridTable = wrapper:tag('table'):addClass('mirklurk-cell-grid')
        :attr('style', 'border-collapse:separate;border-spacing:3px;text-align:center;')
    gridTable:tag('caption'):wikitext(label .. ': ' .. #rows .. ' rows x ' .. width .. ' columns')
    for y, row in ipairs(rows) do
        local tr = gridTable:tag('tr')
        for x = 1, width do
            local cell = row[x]
            local position = 'Row ' .. y .. ', column ' .. x .. ': '
            local td = tr:tag('td')
            if not cell then
                td:addClass('grid-hole'):attr('aria-label', position .. 'empty')
                    :attr('style', 'min-width:3em;height:3em;background:transparent;')
            else
                local visible, description
                if health then
                    visible = cell.armor == 0 and '1 HP' or frame:preprocess(assets().shields[cell.armor])
                    description = '1 HP, ' .. cell.armor .. ' armor layers'
                else
                    visible = cell.low == cell.high and tostring(cell.low) or cell.low .. '-' .. cell.high
                    description = visible .. ' damage'
                end
                td:addClass('grid-cell'):attr('aria-label', position .. description):attr('title', position .. description)
                    :attr('style', 'min-width:3em;height:3em;padding:0.25em;border:2px solid #caa098;background:#852c36;color:#fff;font-weight:bold;')
                    :wikitext(visible)
            end
        end
    end
    local notes
    if health then
        notes = occupied .. ' occupied health cells. [[Health and armor|Reading base health, armor layers, and holes]].'
    else
        notes = 'Sum of occupied-cell ranges: ' .. totalLow .. ' to ' .. totalHigh
            .. '. This is not maximum actual damage: target overlap, armor and modifiers affect the result. '
            .. 'Blank spaces do not strike; a 0-1 cell is occupied and can roll zero damage.\n'
            .. '[[Health and armor|How pattern overlap, rotation, and armor work]].'
    end
    return tostring(wrapper) .. '\n' .. notes
end

function p.health(frame)
    return grid(frame, true)
end

function p.attack(frame)
    return grid(frame, false)
end

return p
