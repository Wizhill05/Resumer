import re
import sys
from pathlib import Path
import markdown
from playwright.sync_api import sync_playwright

# Force UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

def build_pdf_report(md_path: Path, output_path: Path):
    print(f"Reading markdown from {md_path}...")
    md_content = md_path.read_text(encoding="utf-8")
    
    # Split content by '---' to isolate title header from body
    parts = md_content.split("---", 1)
    if len(parts) == 2:
        header_text, body_text = parts
    else:
        header_text = ""
        body_text = md_content
        
    # Extract Title, Subtitle, Author, Date from header_text
    title = "Resumer Project Report"
    subtitle = "Agentic Resume Builder & Intelligent Job Scraping Pipeline"
    author = "Antigravity (AI Assistant)"
    date = "June 2026"
    
    title_match = re.search(r"^#\s+(.+)$", header_text, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        
    subtitle_match = re.search(r"^##\s+(.+)$", header_text, re.MULTILINE)
    if subtitle_match:
        subtitle = subtitle_match.group(1).strip()
        
    # Convert body text to HTML
    body_html = markdown.markdown(body_text, extensions=["extra", "sane_lists", "nl2br"])
    
    # Pre-process diagrams to have the right class
    body_html = body_html.replace("<pre><code>", '<pre class="diagram"><code>')
    
    # Assemble full HTML
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @import url('https://cdn.jsdelivr.net/gh/dreampulse/computer-modern-web-font@master/fonts.css');

        @page {{
            size: A4;
            margin: 2.5cm 2cm 2.5cm 2cm;
        }}

        body {{
            font-family: 'Computer Modern Serif', serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #000;
            background: #fff;
            margin: 0;
            padding: 0;
        }}

        .title-page {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            box-sizing: border-box;
            padding-top: 5cm;
            page-break-after: always;
            height: 100vh;
        }}

        .title-page h1 {{
            font-size: 24pt;
            font-weight: bold;
            margin-bottom: 0.5cm;
            border-bottom: none;
            padding-bottom: 0;
            line-height: 1.2;
        }}

        .title-page h2 {{
            font-size: 16pt;
            font-weight: normal;
            color: #444;
            margin-bottom: 5cm;
            line-height: 1.3;
        }}

        .title-page .author {{
            font-size: 13pt;
            font-weight: bold;
            margin-top: auto;
        }}

        .title-page .date {{
            font-size: 11pt;
            color: #666;
            margin-top: 0.3cm;
        }}

        .content-body {{
            padding-top: 1cm;
        }}

        h1, h2, h3, h4 {{
            font-family: 'Computer Modern Serif', serif;
            font-weight: bold;
            color: #111;
        }}

        h1 {{
            font-size: 16pt;
            margin-top: 1.5cm;
            margin-bottom: 0.6cm;
            border-bottom: 1.5px solid #000;
            padding-bottom: 5px;
            page-break-before: always;
        }}

        .content-body > h1:first-of-type {{
            page-break-before: avoid;
        }}

        h2 {{
            font-size: 13pt;
            margin-top: 1.0cm;
            margin-bottom: 0.4cm;
            border-bottom: 0.5px solid #ccc;
            padding-bottom: 3px;
        }}

        h3 {{
            font-size: 11pt;
            margin-top: 0.8cm;
            margin-bottom: 0.3cm;
            font-style: italic;
        }}

        p {{
            text-align: justify;
            margin-bottom: 0.4cm;
            text-indent: 1.5em;
        }}

        /* Abstract section styling (no text indent) */
        h3 + p {{
            text-indent: 0;
        }}
        
        .content-body > h1 + p {{
            text-indent: 0;
        }}
        
        .content-body > h2 + p {{
            text-indent: 0;
        }}

        ul, ol {{
            margin-bottom: 0.4cm;
            padding-left: 1.5em;
        }}

        li {{
            margin-bottom: 0.15cm;
            text-align: justify;
        }}

        pre, code {{
            font-family: 'Courier New', Courier, monospace;
            background-color: #f7f7f7;
            font-size: 9.5pt;
        }}

        pre.diagram {{
            background-color: #fcfcfc;
            border: 1px solid #ccc;
            padding: 12px;
            overflow-x: auto;
            margin-bottom: 0.5cm;
            line-height: 1.35;
        }}

        code {{
            padding: 2px 4px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div class="title-page">
        <h1>{title}</h1>
        <h2>{subtitle}</h2>
        <div class="author">Prepared by: {author}</div>
        <div class="date">{date}</div>
    </div>
    <div class="content-body">
        {body_html}
    </div>
</body>
</html>
"""

    temp_html_path = output_path.with_suffix(".html")
    print(f"Writing temporary HTML to {temp_html_path}...")
    temp_html_path.write_text(html_template, encoding="utf-8")
    
    print("Launching Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 794, "height": 1123}) # A4 at 96 DPI
        page.emulate_media(media="print")
        
        # Load content and wait for fonts
        page.goto(temp_html_path.as_uri(), wait_until="domcontentloaded")
        try:
            page.evaluate("document.fonts.ready")
        except Exception:
            pass
        
        footer_template = """
        <div style="font-size: 9px; width: 100%; text-align: center; font-family: 'Computer Modern Serif', serif; color: #555; padding-bottom: 1cm;">
            Page <span class="pageNumber"></span> of <span class="totalPages"></span>
        </div>
        """
        
        print(f"Rendering PDF to {output_path}...")
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template='<div style="height: 1cm;"></div>',
            footer_template=footer_template,
            margin={"top": "2.5cm", "bottom": "2.5cm", "left": "2.5cm", "right": "2.5cm"}
        )
        browser.close()
        
    # Clean up temporary HTML
    if temp_html_path.exists():
        temp_html_path.unlink()
        
    print("PDF generation complete!")

if __name__ == "__main__":
    md_file = Path("report.md").resolve()
    pdf_file = Path("report.pdf").resolve()
    build_pdf_report(md_file, pdf_file)
