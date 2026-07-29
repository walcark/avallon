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
  if el.classes:includes("admonition") then
    local style = el.classes:includes("warning")
      and "Encadré Warning" or "Encadré Note"
    el.attributes["custom-style"] = style
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
