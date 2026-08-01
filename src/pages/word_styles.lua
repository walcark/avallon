-- Pandoc filter: map the site's semantic HTML classes onto Word named styles.
--
-- The exporter feeds Pandoc the same HTML the site renders, so colored spans
-- ({rouge}(...) -> <span class="c-rouge">) and admonitions (<div class=
-- "admonition note">) arrive as classed elements. Pandoc only applies a Word
-- style when the `custom-style` attribute is set, so this turns each known
-- class into that attribute. The matching styles are defined in the reference
-- document (see scripts/make_reference_docx.py); an unknown class is left
-- alone.

local span_styles = {
  ["c-rouge"]  = "Rouge",
  ["c-orange"] = "Orange",
  ["c-vert"]   = "Vert",
  ["c-bleu"]   = "Bleu",
  ["c-violet"] = "Violet",
}

function Span(el)
  for _, class in ipairs(el.classes) do
    if span_styles[class] then
      el.attributes["custom-style"] = span_styles[class]
      return el
    end
  end
  return el
end

function Div(el)
  -- Admonition: split the box into a darker title paragraph and a lighter body,
  -- so it reads as the same two-tone card as a code block. The title is always
  -- the first child (its class is lost in the AST, but its position is not).
  if el.classes:includes("admonition") then
    local kind = el.classes:includes("warning") and "Warning" or "Note"
    local blocks = el.content
    if #blocks == 0 then return el end
    local title = pandoc.Div(
      { blocks[1] },
      pandoc.Attr("", {}, { { "custom-style", "Encadré " .. kind .. " Titre" } })
    )
    local out = { title }
    if #blocks > 1 then
      local rest = {}
      for i = 2, #blocks do rest[#rest + 1] = blocks[i] end
      out[#out + 1] = pandoc.Div(
        rest, pandoc.Attr("", {}, { { "custom-style", "Encadré " .. kind } })
      )
    end
    return out
  end
  -- The language caption a code block is rebuilt with (see content.py): its
  -- darker header style sits directly above the lighter code paragraph.
  if el.classes:includes("code-label") then
    el.attributes["custom-style"] = "Code Label"
    return el
  end
  return el
end

-- Give every table equal, full-width columns. Pandoc reads HTML tables with no
-- column widths, so it writes `tblW=auto` with no per-cell width; LibreOffice
-- then collapses the columns and stacks each cell on its own line. Assigning a
-- fractional width per column makes Pandoc emit a fixed, percentage-based
-- layout (tblW=pct 5000) that the converters honor.
function Table(el)
  local n = #el.colspecs
  if n > 0 then
    local w = 1.0 / n
    for i = 1, n do
      el.colspecs[i] = { el.colspecs[i][1], w }
    end
  end
  return el
end
