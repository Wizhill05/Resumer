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
            text-align: justify;
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
        li { margin-bottom: 0.28em; text-align: justify; color: #4a4a4a; }

        dl { display: flex; margin: 0; }
        dl dt, dl dd:not(:last-child) { flex: 1; }
        ul + dl, ol + dl, dl + dl { margin-top: 0.7em; }

        p { margin: 0.2em 0; text-align: justify; }
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
) -> tuple[Path, int, list[dict]]:
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
    Tuple of (Path to the generated PDF file, content height in pixels,
    list of orphan/oversize bullet dicts detected after auto-fit).
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright  # lazy import

    md_path = Path(md_path)
    css_path = Path(css_path)
    output_path = Path(output_path)

    html = _build_html(md_path, css_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Set viewport to exactly match A4 width minus PDF margins (764px) at 96 DPI
        page = browser.new_page(
            viewport={"width": 764, "height": 1123},
        )
        page.emulate_media(media="print")

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

        # Auto-fit: binary search for optimal font-size and line-height
        # Inspired by https://github.com/vladartym/always-fit-resume
        # Pass 1: find the largest font-size (8pt-12pt) at tight line-height
        # Pass 2: expand line-height (1.15x-1.8x) to fill remaining space
        try:
            fit_result = page.evaluate(
                """() => {
                    const body = document.body;
                    const FS_MIN = 8;
                    const FS_MAX = 12;
                    const LH_MIN = 1.15;
                    const LH_MAX = 1.8;

                    // A4 at current print margins: 297mm - 0.2cm top - 0.2cm bottom = 293.6mm
                    // Body padding adds ~1cm each side from the base CSS.
                    // Playwright renders at 96dpi: 1mm = 3.7795px
                    // Available content height ~ 293.6mm * 3.7795 ≈ 1109px
                    // Use scrollHeight vs a single-page limit with a safe buffer to prevent overflows.
                    const PAGE_HEIGHT = 1100;

                    function measure() {
                        return body.scrollHeight;
                    }

                    function applyStyle(fontSize, lineHeight) {
                        body.style.fontSize = fontSize + 'pt';
                        body.style.lineHeight = String(lineHeight);
                    }

                    // Pass 1: binary search for max font-size at tightest line-height
                    let lo = FS_MIN;
                    let hi = FS_MAX;
                    applyStyle(hi, LH_MIN);
                    if (measure() <= PAGE_HEIGHT) {
                        // Already fits at max font size — skip search
                        lo = hi;
                    } else {
                        for (let i = 0; i < 30; i++) {
                            const mid = (lo + hi) / 2;
                            applyStyle(mid, LH_MIN);
                            if (measure() <= PAGE_HEIGHT) {
                                lo = mid;
                            } else {
                                hi = mid;
                            }
                            if (hi - lo < 0.01) break;
                        }
                    }
                    const fontSize = Math.floor(lo * 100) / 100;

                    // Pass 2: binary search for max line-height at locked font-size
                    let lhLo = LH_MIN;
                    let lhHi = LH_MAX;
                    applyStyle(fontSize, lhHi);
                    if (measure() <= PAGE_HEIGHT) {
                        lhLo = lhHi;
                    } else {
                        for (let i = 0; i < 30; i++) {
                            const mid = (lhLo + lhHi) / 2;
                            applyStyle(fontSize, mid);
                            if (measure() <= PAGE_HEIGHT) {
                                lhLo = mid;
                            } else {
                                lhHi = mid;
                            }
                            if (lhHi - lhLo < 0.001) break;
                        }
                    }
                    const lineHeight = Math.floor(lhLo * 1000) / 1000;

                    // Apply final values
                    applyStyle(fontSize, lineHeight);

                    return { fontSize, lineHeight, contentHeight: measure() };
                }"""
            )
            print(
                f"  Auto-fit: font-size={fit_result['fontSize']:.2f}pt, "
                f"line-height={fit_result['lineHeight']:.3f}, "
                f"content-height={fit_result['contentHeight']}px"
            )
        except Exception as err:
            print(f"⚠️  Auto-fit script failed: {err}")

        # ── Pass 3: Orphan line detection ─────────────────────────────────
        # After auto-fit locks font-size and line-height, measure every <li>
        # to find orphan lines (wrapping to a mostly-empty second line) and
        # oversize bullets (exceeding 2 rendered lines).
        orphan_data: list[dict] = []
        try:
            orphan_result = page.evaluate(
                """() => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    const results = [];

                    const allLi = document.querySelectorAll('li');
                    for (const li of allLi) {
                        const text = li.textContent.trim();
                        if (!text) continue;

                        // Compute single-line height from the li's own computed style
                        const liStyle = window.getComputedStyle(li);
                        const singleLineH = parseFloat(liStyle.lineHeight);
                        if (!singleLineH || singleLineH <= 0) continue;

                        const liHeight = li.getBoundingClientRect().height;
                        const actualLines = liHeight / singleLineH;

                        // Determine section by walking backwards from parent <ul>
                        let section = 'unknown';
                        let sectionItemIndex = 0;
                        const parentUl = li.closest('ul');
                        if (parentUl) {
                            let prev = parentUl.previousElementSibling;
                            while (prev) {
                                if (prev.tagName === 'H2') {
                                    const h2Text = prev.textContent.trim().toLowerCase();
                                    if (h2Text.includes('project')) section = 'projects';
                                    else if (h2Text.includes('experience')) section = 'experience';
                                    else if (h2Text.includes('activit') || h2Text.includes('achievement')) section = 'activities';
                                    break;
                                }
                                if (prev.tagName === 'UL') sectionItemIndex++;
                                prev = prev.previousElementSibling;
                            }
                        }

                        const bulletIndex = parentUl
                            ? Array.from(parentUl.children).indexOf(li)
                            : 0;

                        // Measure chars-per-line using canvas text measurement
                        ctx.font = liStyle.font;
                        const textWidth = ctx.measureText(text).width;
                        const containerWidth = li.clientWidth;
                        const avgCharWidth = textWidth / text.length;
                        const charsPerLine = Math.floor(containerWidth / avgCharWidth);

                        // Height-based line count (rounded — getBoundingClientRect
                        // always yields integer multiples of line-height)
                        const lineCount = Math.round(actualLines);
                        if (lineCount <= 1) continue; // single line, no issue

                        // Canvas-based estimate of last-line fill:
                        // textWidth = total unwrapped width; containerWidth = li box
                        const textFillLines = textWidth / containerWidth;
                        const lastLineFillRaw = textFillLines - (lineCount - 1);
                        const lastLineFill = Math.max(0, Math.min(1, lastLineFillRaw));

                        if (lineCount === 2 && lastLineFill < 0.45) {
                            // ORPHAN: wraps to 2nd line but it's < 45% full
                            const targetMin = Math.floor(charsPerLine * 1.82);
                            const targetMax = Math.floor(charsPerLine * 1.95);
                            results.push({
                                fix_type: 'expand',
                                section,
                                sectionItemIndex,
                                bulletIndex,
                                text,
                                currentChars: text.length,
                                renderedLines: lineCount,
                                charsPerLine,
                                targetCharsMin: targetMin,
                                targetCharsMax: targetMax,
                                charsToAddMin: Math.max(0, targetMin - text.length),
                                charsToAddMax: Math.max(0, targetMax - text.length),
                            });
                        } else if (lineCount > 2) {
                            // OVERSIZE: exceeds 2 rendered lines
                            const targetMax = Math.floor(charsPerLine * 1.95);
                            results.push({
                                fix_type: 'shorten',
                                section,
                                sectionItemIndex,
                                bulletIndex,
                                text,
                                currentChars: text.length,
                                renderedLines: lineCount,
                                charsPerLine,
                                targetCharsMin: Math.floor(charsPerLine * 1.82),
                                targetCharsMax: targetMax,
                            });
                        }
                    }
                    return results;
                }"""
            )
            orphan_data = orphan_result or []
            if orphan_data:
                expand_count = sum(1 for o in orphan_data if o["fix_type"] == "expand")
                shorten_count = sum(1 for o in orphan_data if o["fix_type"] == "shorten")
                print(f"  Orphan detection: {expand_count} orphan(s), {shorten_count} oversize bullet(s)")
            else:
                print("  Orphan detection: no orphan lines found")
        except Exception as err:
            print(f"⚠️  Orphan detection failed: {err}")

        # Measure the content height after auto-fit
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
    return output_path, content_height, orphan_data


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
