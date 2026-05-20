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


def _looks_like_windows_abs_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", value))


def _is_external_or_builtin_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(
        (
            "http://",
            "https://",
            "data:",
            "blob:",
            "about:",
            "javascript:",
            "file://",
        )
    )


def _resolve_local_asset_ref(value: str, base_dirs: list[Path]) -> str:
    """
    Resolve local paths (Windows absolute, workspace-relative, css-relative) to file:// URLs.
    Keeps external URLs unchanged.
    """
    raw = value.strip().strip("\"'")
    if not raw:
        return value
    if _is_external_or_builtin_url(raw):
        return raw

    candidates: list[Path] = []
    if _looks_like_windows_abs_path(raw) or raw.startswith("\\\\"):
        candidates.append(Path(raw))
    else:
        rel = Path(raw)
        for base in base_dirs:
            candidates.append(base / rel)
        # Also allow paths relative to current working directory.
        candidates.append(Path.cwd() / rel)

    for candidate in candidates:
        try:
            p = candidate.expanduser().resolve()
        except Exception:
            continue
        if p.exists():
            try:
                return p.as_uri()
            except Exception:
                continue

    return raw


def _rewrite_css_asset_urls(css_text: str, css_dir: Path) -> str:
    pattern = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", flags=re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        quote = match.group(1) or ""
        ref = match.group(2) or ""
        resolved = _resolve_local_asset_ref(ref, [css_dir])
        return f"url({quote}{resolved}{quote})"

    return pattern.sub(repl, css_text)


def _rewrite_html_img_src(html_text: str, base_dirs: list[Path]) -> str:
    pattern = re.compile(
        r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)(\2)',
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        prefix, quote, src_value, suffix_quote = match.groups()
        resolved = _resolve_local_asset_ref(src_value, base_dirs)
        return f"{prefix}{quote}{resolved}{suffix_quote}"

    return pattern.sub(repl, html_text)


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
    page_css = _rewrite_css_asset_urls(page_css, css_path.parent)

    # 5. Print-friendly base styles
    base_css = textwrap.dedent("""
        @import url('https://cdn.jsdelivr.net/gh/dreampulse/computer-modern-web-font@master/fonts.css');

        * { box-sizing: border-box; }

        body {
            font-family: 'Computer Modern Serif', serif;
            font-size: 10pt;
            line-height: 1.5;
            margin: 0;
            padding: 1.0cm 1.4cm;
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
    html = textwrap.dedent(f"""
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

    # Resolve local image paths (e.g., Windows paths in truth.json photo.link).
    return _rewrite_html_img_src(html, [md_path.parent, css_path.parent])


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
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright  # lazy import

    md_path = Path(md_path)
    css_path = Path(css_path)
    output_path = Path(output_path)

    html = _build_html(md_path, css_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Use DOM readiness instead of networkidle. The template references
        # external font/icon CDNs, and waiting for full network idle can hang.
        page.set_content(html, wait_until="domcontentloaded")

        # Wait for Iconify to replace all iconify spans with rendered SVGs.
        # Iconify sets a 'data-loaded' attribute on the root script tag when done,
        # and replaces .iconify spans with <svg> elements.
        try:
            page.wait_for_function(
                """() => {
                    const spans = document.querySelectorAll('.iconify');
                    if (spans.length === 0) return true;          // no icons to render
                    const svgs  = document.querySelectorAll('svg.iconify');
                    return svgs.length >= spans.length;           // all replaced
                }""",
                timeout=10_000,
            )
        except PlaywrightTimeoutError:
            print("⚠️  Iconify CDN not ready in time; continuing without icon wait.")

        # Wait until images are fully loaded (prevents partially painted photos)
        # and let web fonts settle before PDF capture.
        try:
            page.wait_for_function(
                """() => {
                    const imgs = Array.from(document.images || []);
                    return imgs.every((img) => img.complete);
                }""",
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
            print("⚠️  Some images did not finish loading in time; continuing.")

        try:
            page.evaluate(
                """async () => {
                    if (document.fonts && document.fonts.ready) {
                        try { await document.fonts.ready; } catch (_) {}
                    }
                    const imgs = Array.from(document.images || []);
                    await Promise.all(
                        imgs.map(async (img) => {
                            if (!img.complete) return;
                            if (typeof img.decode === "function") {
                                try { await img.decode(); } catch (_) {}
                            }
                        })
                    );
                }"""
            )
        except Exception:
            pass

        page.wait_for_timeout(200)

        # Apply Dynamic DOM Micro-Squeezing Typesetting Optimizer
        try:
            page.evaluate(
                """() => {
                    const elements = document.querySelectorAll('.resume-body li, .resume-body p');
                    for (const el of elements) {
                        if (!el.textContent.trim()) continue;

                        const originalHTML = el.innerHTML;

                        function wrapWords(node) {
                            if (node.nodeType === Node.TEXT_NODE) {
                                const text = node.textContent;
                                const words = text.split(/(\s+)/);
                                const fragment = document.createDocumentFragment();
                                for (const word of words) {
                                    if (word.trim().length > 0) {
                                        const span = document.createElement('span');
                                        span.className = 'word-span';
                                        span.textContent = word;
                                        fragment.appendChild(span);
                                    } else {
                                        fragment.appendChild(document.createTextNode(word));
                                    }
                                }
                                node.parentNode.replaceChild(fragment, node);
                            } else if (node.nodeType === Node.ELEMENT_NODE) {
                                if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
                                const children = Array.from(node.childNodes);
                                for (const child of children) {
                                    wrapWords(child);
                                }
                            }
                        }

                        wrapWords(el);

                        const spans = Array.from(el.querySelectorAll('.word-span'));
                        if (spans.length === 0) {
                            el.innerHTML = originalHTML;
                            continue;
                        }

                        const lines = [];
                        let currentLineTop = -99999;
                        let currentLine = [];
                        for (const span of spans) {
                            const top = span.getBoundingClientRect().top;
                            if (Math.abs(top - currentLineTop) > 3) {
                                if (currentLine.length > 0) {
                                    lines.push(currentLine);
                                }
                                currentLine = [span];
                                currentLineTop = top;
                            } else {
                                currentLine.push(span);
                            }
                        }
                        if (currentLine.length > 0) {
                            lines.push(currentLine);
                        }

                        el.innerHTML = originalHTML;

                        const totalLines = lines.length;
                        if (totalLines <= 1) continue;

                        const lastLineWords = lines[totalLines - 1];
                        const lastLineWordCount = lastLineWords.length;
                        const lastLineText = lastLineWords.map(s => s.textContent).join(' ').trim();
                        const lastLineCharCount = lastLineText.length;

                        // Detect orphan word on the last line (widow)
                        const isWidow = (lastLineWordCount <= 2) || (lastLineWordCount <= 3 && lastLineCharCount <= 18);

                        if (isWidow) {
                            const originalHeight = el.offsetHeight;
                            let success = false;

                            // Try squeezing up to -0.04em
                            for (let ls = -0.005; ls >= -0.04; ls -= 0.005) {
                                el.style.letterSpacing = `${ls}em`;
                                if (el.offsetHeight < originalHeight) {
                                    success = true;
                                    break;
                                }
                            }

                            if (!success) {
                                el.style.letterSpacing = 'normal';
                            }
                        }
                    }
                }"""
            )
        except Exception as err:
            print(f"⚠️  Spacing optimizer script failed: {err}")

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
