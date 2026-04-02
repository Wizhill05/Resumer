"""
makepdf.py – Convert template.md + template.css into a PDF resume.

Requirements:
    uv add markdown python-frontmatter playwright
    uv run playwright install chromium
"""

import re
import sys
import textwrap
from pathlib import Path

import frontmatter  # python-frontmatter
import markdown as md_lib  # markdown

# Force UTF-8 output so emoji in print() don't crash on Windows (cp1252 default)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_header_html(meta: dict) -> str:
    """Render the YAML front-matter into a resume header block."""
    name = meta.get("name", "")
    items: list = meta.get("header", [])

    lines = ['<div class="resume-header">']
    lines.append(f"  <h1>{name}</h1>")
    lines.append('  <div class="resume-header-items">')

    for item in items:
        text = item.get("text", "")
        link = item.get("link", "")
        new_line = item.get("newLine", False)

        if new_line:
            lines.append("  <br>")

        if link:
            inner = f'<a href="{link}">{text}</a>'
        else:
            inner = text

        lines.append(f'    <span class="resume-header-item">{inner}</span>')

    lines.append("  </div>")
    lines.append("</div>")
    return "\n".join(lines)


def _adapt_css(css_text: str) -> str:
    """
    Strip the '#resume-preview ' scope prefix from all selectors so the CSS
    works on a standalone HTML page (no Vue wrapper).
    Also removes '.dark ' dark-mode wrapper selectors.
    """
    adapted = re.sub(r"#resume-preview\s+", "", css_text)
    adapted = re.sub(r"\.dark\s+", "", adapted)
    return adapted


def _md_inline(text: str) -> str:
    """Render a single line of markdown to inline HTML (strips the wrapping <p> tag)."""
    _md = md_lib.Markdown()
    html = _md.convert(text.strip())
    # Remove the <p>...</p> wrapper that markdown adds to single lines
    html = re.sub(r"^<p>(.*?)</p>$", r"\1", html.strip(), flags=re.DOTALL)
    return html


def _preprocess_tilde(body: str) -> str:
    """
    Convert the '~ right-text' row syntax into definition-list HTML so the
    existing CSS (dl { display: flex }) places items left/right automatically.

    Pattern – consecutive lines with no blank line between them:
        Left text
        ~ Right text 1
        ~ Right text 2

    Becomes:
        <dl><dt>Left text</dt><dd>Right text 1</dd><dd>Right text 2</dd></dl>
    """
    lines = body.splitlines()
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        tilde_lines: list[str] = []

        # Collect consecutive '~ ...' lines immediately after this line
        while j < len(lines) and lines[j].startswith("~ "):
            tilde_lines.append(lines[j][2:])  # strip leading '~ '
            j += 1

        if tilde_lines:
            dt = _md_inline(line)
            dds = "".join(f"<dd>{_md_inline(t)}</dd>" for t in tilde_lines)
            result.append(f"<dl><dt>{dt}</dt>{dds}</dl>")
            i = j
        else:
            result.append(line)
            i += 1

    return "\n".join(result)


def _build_html(md_path: Path, css_path: Path) -> str:
    """Parse template.md + template.css and return a complete HTML string."""
    # 1. Parse front-matter + markdown body
    post = frontmatter.load(md_path)
    meta: dict = post.metadata
    body: str = post.content

    # 2. Pre-process '~ right-text' syntax → <dl> HTML, then render markdown
    body_preprocessed = _preprocess_tilde(body)
    body_html = md_lib.markdown(
        body_preprocessed, extensions=["extra", "sane_lists", "nl2br"]
    )

    # 3. Build header block from front-matter
    header_html = _build_header_html(meta)

    # 4. Load & adapt CSS
    raw_css = css_path.read_text(encoding="utf-8")
    page_css = _adapt_css(raw_css)

    # 5. Print-friendly base styles
    base_css = textwrap.dedent("""
        @import url('https://cdn.jsdelivr.net/gh/dreampulse/computer-modern-web-font@master/fonts.css');

        * { box-sizing: border-box; }

        body {
            font-family: 'Computer Modern Serif', serif;
            font-size: 10pt;
            line-height: 1.5;
            margin: 0;
            padding: 0.8cm 1cm;
            color: black;
            background: white;
        }

        a { color: #1A0DAB; text-decoration: none; }

        .resume-header { text-align: center; margin-bottom: 1em; }
        .resume-header h1 { margin: 0 0 6px; }
        .resume-header-item:not(:last-child)::after { content: " | "; }

        h2 {
            font-size: 1.1em;
            font-weight: bold;
            border-bottom: 1px solid currentColor;
            margin: 0.8em 0 0.3em;
            padding-bottom: 2px;
        }

        h3 { font-size: 1em; font-weight: bold; margin: 0.5em 0 0.2em; }

        ul { padding-left: 1.4em; margin: 0.2em 0; list-style-type: circle; }
        li { margin-bottom: 0.15em; }

        dl { display: flex; margin: 0; }
        dl dt, dl dd:not(:last-child) { flex: 1; }

        p { margin: 0.2em 0; }
    """)

    # 6. Assemble full HTML document
    return textwrap.dedent(f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Resume – {meta.get("name", "")}</title>
            <!-- Iconify: renders data-icon spans as SVG icons -->
            <script src="https://code.iconify.design/3/3.1.1/iconify.min.js"></script>
            <style>
        {base_css}
        {page_css}
            </style>
        </head>
        <body>
            {header_html}
            <div class="resume-body">
                {body_html}
            </div>
        </body>
        </html>
    """).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_pdf(
    md_path: str | Path = "template/template.md",
    css_path: str | Path = "template/template.css",
    output_path: str | Path = "output/resume.pdf",
) -> tuple[Path, int]:
    """
    Generate a PDF resume from a Markdown template and a CSS stylesheet.

    Uses a headless Chromium browser (via Playwright) for rendering, so no
    native GTK/Pango libraries are required.

    Parameters
    ----------
    md_path     : Path to the Markdown resume template (with YAML front-matter).
    css_path    : Path to the CSS stylesheet.
    output_path : Destination path for the generated PDF.

    Returns
    -------
    Tuple of (Path to the generated PDF file, content height in pixels).
    """
    from playwright.sync_api import sync_playwright  # lazy import

    md_path = Path(md_path)
    css_path = Path(css_path)
    output_path = Path(output_path)

    html = _build_html(md_path, css_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Load HTML; use a file base-URL so relative assets (images etc.) resolve
        page.set_content(html, wait_until="networkidle")

        # Wait for Iconify to replace all iconify spans with rendered SVGs.
        # Iconify sets a 'data-loaded' attribute on the root script tag when done,
        # and replaces .iconify spans with <svg> elements.
        page.wait_for_function(
            """() => {
                const spans = document.querySelectorAll('.iconify');
                if (spans.length === 0) return true;          // no icons to render
                const svgs  = document.querySelectorAll('svg.iconify');
                return svgs.length >= spans.length;           // all replaced
            }""",
            timeout=10_000,
        )

        # Measure the content height before generating the PDF
        content_height = page.evaluate("() => document.body.scrollHeight")

        page.pdf(
            path=str(output_path),
            format="A4",
            margin={
                "top": "0.2cm",
                "bottom": "0.2cm",
                "left": "0.4cm",
                "right": "0.4cm",
            },
            print_background=True,
        )
        browser.close()

    print(f"✅  PDF written to: {output_path.resolve()}")
    return output_path, content_height


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a PDF resume from Markdown + CSS."
    )
    parser.add_argument(
        "--md", default="template/template.md", help="Markdown template path"
    )
    parser.add_argument(
        "--css", default="template/template.css", help="CSS stylesheet path"
    )
    parser.add_argument("-o", default="output/resume.pdf", help="Output PDF path")
    args = parser.parse_args()

    generate_pdf(md_path=args.md, css_path=args.css, output_path=args.o)
