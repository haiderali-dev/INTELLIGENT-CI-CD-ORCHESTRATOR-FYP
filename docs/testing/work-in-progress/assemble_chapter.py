"""Assemble Chapter 8 from its draft.

    assemble_chapter.py <draft.md> <out.md>

- A figure marker, [[FIGURE <file> {F:<label>} | <caption>]], becomes the image (figures/<file>.png)
  and a bold caption.
- Tables and figures are numbered 8.1, 8.2, ... in the order their captions appear, and every
  {T:label} and {F:label} becomes its number.
- Anything left unresolved is reported: a label with no caption, or a [[PLACEHOLDER]] not filled.
"""

import re
import sys
from pathlib import Path

LF = chr(10)
text = Path(sys.argv[1]).read_text(encoding="utf-8")


def figure(match: re.Match[str]) -> str:
    file, label, caption = match.group(1), match.group(2), match.group(3).strip()
    return (f"![Figure {{F:{label}}}: {caption}](figures/{file}.png)" + LF + LF
            + f"**Figure {{F:{label}}}: {caption}**")


text = re.sub(r"\[\[FIGURE ([a-z0-9-]+) \{F:([a-z0-9]+)\} \| ([^\]]+)\]\]", figure, text)


def numbered(kind: str, prefix: str) -> dict[str, str]:
    order: list[str] = []
    for match in re.finditer(r"\*\*" + kind + r" \{" + prefix + r":([a-z0-9]+)\}:", text):
        if match.group(1) not in order:
            order.append(match.group(1))
    return {label: f"8.{index}" for index, label in enumerate(order, 1)}


tables, figures = numbered("Table", "T"), numbered("Figure", "F")
uncaptioned = sorted({f"T:{m}" for m in re.findall(r"\{T:([a-z0-9]+)\}", text)} - {f"T:{t}" for t in tables}
                     | {f"F:{m}" for m in re.findall(r"\{F:([a-z0-9]+)\}", text)} - {f"F:{f}" for f in figures})
text = re.sub(r"\{T:([a-z0-9]+)\}", lambda m: tables.get(m.group(1), "??" + m.group(1)), text)
text = re.sub(r"\{F:([a-z0-9]+)\}", lambda m: figures.get(m.group(1), "??" + m.group(1)), text)
unfilled = sorted(set(re.findall(r"\[\[[A-Z0-9_]+\]\]", text)))
Path(sys.argv[2]).write_text(text, encoding="utf-8", newline=LF)
print(f"{len(tables)} tables, {len(figures)} figures")
print("labels with no caption:", uncaptioned or "none")
print("placeholders unfilled:", unfilled or "none")
