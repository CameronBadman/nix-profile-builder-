"""Copy the recorded live pitch (demo/recorded-pitch.txt) verbatim into backup slides B1/B2.

Run after re-recording:  python3 presentation/sync-backups.py
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "presentation" / "index.html"
REC = ROOT / "demo" / "recorded-pitch.txt"

ANSI = re.compile(r"\x1b\[([0-9;]*)m")
CLASS = {"1;32": "g", "1;31": "r", "1;33": "y", "36": "b", "2": "mute", "1": "bold"}


def to_html(text):
    out, open_span = [], False
    pos = 0
    for m in ANSI.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        if open_span:
            out.append("</span>")
            open_span = False
        cls = CLASS.get(m.group(1))
        if cls:
            out.append(f'<span class="{cls}">')
            open_span = True
        pos = m.end()
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    return "".join(out)


def section(lines, start_marker, end_marker=None):
    """Lines from the `$` command after start_marker up to end_marker (exclusive)."""
    plain = [ANSI.sub("", l) for l in lines]
    s = next(i for i, l in enumerate(plain) if start_marker in l)
    s = next(i for i in range(s, len(plain)) if plain[i].startswith("$ "))
    e = next((i for i in range(s, len(plain)) if end_marker and end_marker in plain[i]), len(plain))
    body = lines[s:e]
    while body and not ANSI.sub("", body[-1]).strip():
        body.pop()
    return to_html("\n".join(body))


lines = REC.read_text().splitlines()
b1 = section(lines, "1/2", "2/2")
b2 = section(lines, "2/2")
deck = DECK.read_text()
for tag, body in (("B1", b1), ("B2", b2)):
    deck, n = re.subn(rf'(<div class="term rec" id="rec-{tag}">).*?(</div>)',
                      lambda m: m.group(1) + body + m.group(2), deck, flags=re.S)
    assert n == 1, f"marker rec-{tag} not found"
DECK.write_text(deck)
print("synced B1/B2 from", REC.relative_to(ROOT))
