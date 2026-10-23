"""
Builds the guide: docs/Call-Centre-Dashboard-Guide.pdf

    python docs/guide/build_guide.py           # HTML, then PDF (needs Microsoft Edge or Google Chrome)
    python docs/guide/build_guide.py --html    # HTML only: docs/guide/build/guide.html

Where everything comes from:
    chapters/*.md     the written chapters, in Markdown (Parts 1, 2, 4 and 5, and the glossary)
    notes/*.py        what each line of code does: one entry per source file (Part 3)
    images/*.png      screenshots used by the chapters
    the code itself   read straight from the project, so the listings always match the code

Each explanation is pinned to a line by a piece of that line's text (its "anchor"), not by
its line number. If the code changes and an anchor no longer matches, the build stops and
says which one. That way the guide can't quietly drift away from the code.

Needs the developer packages:  pip install -r requirements-dev.txt
"""
import argparse
import base64
import datetime
import html
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

GUIDE = Path(__file__).resolve().parent         # docs/guide
PROJECT = GUIDE.parent.parent                   # the project folder
BUILD = GUIDE / "build"                         # generated HTML (not kept in Git)
PDF = PROJECT / "docs" / "Call-Centre-Dashboard-Guide.pdf"

# Which Pygments "lexer" (colouring rules) to use for each kind of file
LEXERS = {
    ".py": "python", ".js": "javascript", ".html": "html+django", ".css": "css", ".toml": "toml",
    ".yml": "yaml", ".txt": "text", ".md": "markdown", ".example": "bash", ".gitignore": "text",
    ".gitattributes": "text",
}

# Where Edge or Chrome usually live, for turning the HTML into a PDF
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "microsoft-edge", "google-chrome", "chromium", "chromium-browser",
]


class GuideError(Exception):
    """Something in the chapters or notes doesn't match the code."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def md(text, inline=False):
    """Markdown -> HTML. inline=True drops the surrounding <p> for one-line notes."""
    out = markdown.markdown(text.strip(), extensions=["tables", "fenced_code", "codehilite"],
                            extension_configs={"codehilite": {"guess_lang": False, "css_class": "hl"}})
    if inline and out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        out = out[3:-4]
    return out


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def lexer_for(path):
    suffix = path.suffix or path.name  # ".gitignore" has no suffix, only a name
    return get_lexer_by_name(LEXERS.get(suffix, "text"))


def embed_images(page_html):
    """Put each <img src="images/x.png"> inside the HTML itself, so the file stands alone."""
    def inline(match):
        src = match.group(1)
        path = GUIDE / src
        if not path.exists():
            raise GuideError(f"Image not found: {src}")
        data = base64.b64encode(path.read_bytes()).decode()
        return f'src="data:image/png;base64,{data}"'
    return re.sub(r'src="(images/[^"]+)"', inline, page_html)


def load_notes():
    """Every notes/*.py file, in name order. Each defines FILES: a list of file entries."""
    entries = []
    for path in sorted((GUIDE / "notes").glob("n*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        entries.extend(module.FILES)
    return entries


# ---------------------------------------------------------------------------
# Part 3: the code, line by line
# ---------------------------------------------------------------------------

def pin_notes(entry, lines):
    """
    Turn each (anchor, explanation) into (line number, explanation).
    Anchors are searched in order: each one is looked for from the line after the previous match,
    so a common piece of text like "return None" finds the right occurrence.
    An entry can also be (anchor, explanation, end_anchor) to explain several lines at once.
    """
    pinned, cursor = [], 0
    for note in entry.get("lines", []):
        anchor, text = note[0], note[1]
        end_anchor = note[2] if len(note) > 2 else None
        for i in range(cursor, len(lines)):
            if anchor in lines[i]:
                start = i
                break
        else:
            raise GuideError(f"{entry['path']}: no line containing {anchor!r} after line {cursor + 1}")
        end = start
        if end_anchor:
            for i in range(start, len(lines)):
                if end_anchor in lines[i]:
                    end = i
                    break
            else:
                raise GuideError(
                    f"{entry['path']}: no line containing end anchor {end_anchor!r} after line {start + 1}"
                )
        pinned.append((start + 1, end + 1, text))
        cursor = start + 1
    return pinned


def chunks(lines, smallest=14):
    """
    Split a file into pieces to show one at a time, with their notes underneath.
    A piece starts at a top-level line (nothing in front of it) that follows a blank line;
    small pieces are joined until they are at least `smallest` lines long.
    Returns (first line, last line) pairs, counting from 1.
    """
    starts = [0]
    for i in range(1, len(lines)):
        line = lines[i]
        if lines[i - 1].strip() == "" and line.strip() and not line[0].isspace() and line[0] not in ")]}":
            starts.append(i)
    pieces = [(s, (starts[n + 1] if n + 1 < len(starts) else len(lines)) - 1) for n, s in enumerate(starts)]

    joined = []
    for start, end in pieces:
        if joined and joined[-1][1] - joined[-1][0] + 1 < smallest:
            joined[-1] = (joined[-1][0], end)
        else:
            joined.append((start, end))
    # Drop blank lines at the end of each piece
    result = []
    for start, end in joined:
        while end > start and not lines[end].strip():
            end -= 1
        result.append((start + 1, end + 1))
    return result


def render_file(entry, number):
    path = PROJECT / entry["path"]
    if not path.exists():
        raise GuideError(f"Source file not found: {entry['path']}")
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    notes = pin_notes(entry, lines)
    lexer = lexer_for(path)

    toc_text = f'{number}. {entry["path"]} — {entry.get("title", "")}'.rstrip(" —")
    out = [f'<section class="file" id="file-{slug(entry["path"])}">',
           f'<h2 data-toc="{html.escape(toc_text)}" data-level="3">'
           f'<span class="num">{number}</span> <code>{html.escape(entry["path"])}</code>'
           f'<span class="file-title">{html.escape(entry.get("title", ""))}</span></h2>',
           f'<div class="intro">{md(entry["intro"])}</div>' if entry.get("intro") else "",
           f'<p class="meta">{len(lines)} lines</p>']

    if entry.get("listing", True):
        for first, last in chunks(lines):
            piece = "\n".join(lines[first - 1:last]) + "\n"
            formatter = HtmlFormatter(linenos="inline", linenostart=first, cssclass="code", wrapcode=True)
            out.append(highlight(piece, lexer, formatter))
            here = [n for n in notes if first <= n[0] <= last]
            if here:
                rows = []
                for start, end, text in here:
                    where = f"{start}" if start == end else f"{start}–{end}"
                    code = lines[start - 1].strip()
                    if len(code) > 58:
                        code = code[:56] + " …"
                    rows.append(f"<tr><td class='ln'>{where}</td><td class='cl'><code>{html.escape(code)}</code></td>"
                                f"<td>{md(text, inline=True)}</td></tr>")
                out.append("<table class='notes'><thead><tr><th>Line</th><th>Code</th><th>What it does</th></tr>"
                           f"</thead><tbody>{''.join(rows)}</tbody></table>")
    out.append("</section>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The whole document
# ---------------------------------------------------------------------------

def chapter(name):
    path = GUIDE / "chapters" / name
    if not path.exists():
        raise GuideError(f"Chapter not found: {name}")
    return md(path.read_text(encoding="utf-8"))


def add_heading_ids(page_html):
    """
    Give every <h1>/<h2> an id, and return the table of contents built from them.
    A heading can set its own contents text and level with data-toc="..." and data-level="3"
    (the file headings in Part 3 do, to read "3. calls/client.py — what it is" one level deeper).
    """
    toc, used = [], set()

    def tag(match):
        level, attrs, text = match.group(1), match.group(2), match.group(3)
        if 'class="no-toc"' in attrs:
            return match.group(0)
        custom = re.search(r'data-toc="([^"]*)"', attrs)
        plain = custom.group(1) if custom else re.sub(r"<[^>]+>", "", text)
        plain = html.unescape(plain)  # the text is escaped again when the contents are written
        custom_level = re.search(r'data-level="(\d)"', attrs)
        if custom_level:
            level = custom_level.group(1)
        hid = re.search(r'id="([^"]+)"', attrs)
        hid = hid.group(1) if hid else slug(plain)
        while hid in used:
            hid += "-x"
        used.add(hid)
        toc.append((int(level), hid, plain))
        attrs = re.sub(r'\s*id="[^"]+"', "", attrs)
        tag_level = match.group(1)  # the HTML tag keeps its own level; only the contents entry changes
        return f'<h{tag_level}{attrs} id="{hid}">{text}</h{tag_level}>'

    page_html = re.sub(r"<h([12])([^>]*)>(.*?)</h\1>", tag, page_html, flags=re.S)
    items = []
    for level, hid, text in toc:
        items.append(f'<li class="toc{level}"><a href="#{hid}">{html.escape(text)}</a></li>')
    return page_html, f'<nav class="toc"><h1 class="no-toc">Contents</h1><ul>{"".join(items)}</ul></nav>'


def build_html():
    files = load_notes()
    today = datetime.date.today().strftime("%d %B %Y")

    part3 = [md((GUIDE / "chapters" / "03-code.md").read_text(encoding="utf-8"))]
    group = None
    for n, entry in enumerate(files, start=1):
        if entry.get("group") and entry["group"] != group:
            group = entry["group"]
            first = " first" if group == files[0].get("group") else ""  # the first follows the intro on its page
            part3.append(f'<h2 class="group{first}">{html.escape(group)}</h2>')
        part3.append(render_file(entry, n))

    body = "\n".join([
        f'''<section class="cover">
              <p class="kicker">Build guide</p>
              <h1 class="no-toc">Call Centre Dashboard</h1>
              <p class="subtitle">How it works, how to build it yourself, and what every line of code does</p>
              <p class="meta">Django · Python · JavaScript · Chart.js · HoduCC API<br>
                 Generated {today} from the code in this folder</p>
            </section>''',
        '<div class="toc-here"></div>',
        f'<section class="part">{chapter("01-introduction.md")}</section>',
        f'<section class="part">{chapter("02-rebuild.md")}</section>',
        f'<section class="part code-part">{"".join(part3)}</section>',
        f'<section class="part">{chapter("04-hoducc-api.md")}</section>',
        f'<section class="part">{chapter("05-run-test-deploy.md")}</section>',
        f'<section class="part">{chapter("06-glossary.md")}</section>',
    ])
    body, toc = add_heading_ids(body)
    body = body.replace('<div class="toc-here"></div>', toc)
    body = embed_images(body)

    css = (GUIDE / "guide.css").read_text(encoding="utf-8")
    code_css = HtmlFormatter(style="friendly").get_style_defs([".code", ".hl"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Call Centre Dashboard - Build guide</title>
<style>{css}\n{code_css}</style></head>
<body>{body}</body></html>"""


def find_browser():
    for candidate in BROWSERS:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def make_pdf(html_path):
    browser = find_browser()
    if not browser:
        raise GuideError("No Edge or Chrome found to make the PDF. Open the HTML and print it to PDF instead: "
                         f"{html_path}")
    PDF.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={PDF}", html_path.resolve().as_uri()],
        check=True, capture_output=True, timeout=300,
    )
    if not PDF.exists() or PDF.stat().st_size < 10_000:
        raise GuideError(f"The browser didn't write the PDF: {PDF}")


def main():
    parser = argparse.ArgumentParser(description="Build the call-centre dashboard guide.")
    parser.add_argument("--html", action="store_true", help="only write the HTML, no PDF")
    args = parser.parse_args()
    try:
        page = build_html()
        BUILD.mkdir(exist_ok=True)
        html_path = BUILD / "guide.html"
        html_path.write_text(page, encoding="utf-8")
        print(f"HTML: {html_path}")
        if not args.html:
            make_pdf(html_path)
            print(f"PDF:  {PDF}")
    except GuideError as exc:
        sys.exit(f"Guide not built: {exc}")


if __name__ == "__main__":
    main()
