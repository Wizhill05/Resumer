"""
parse_indeed_html.py
====================
Parses the downloaded Indeed HTML file to extract job information
from the job_seen_beacon elements and saves it to a JSON file.
"""

import json
from pathlib import Path
from scrapling.parser import Selector
from dotenv import load_dotenv

OUTPUT_DIR = Path(__file__).parent / "output"
INPUT_HTML = OUTPUT_DIR / "indeed_raw.html"
OUTPUT_JSON = OUTPUT_DIR / "parsed_jobs.json"

# Load environment variables
load_dotenv(Path(__file__).parents[2] / ".env.local")

def extract_text(element):
    """Recursively extract and join all text from an element and its descendants."""
    if not element:
        return ""
    texts = element.xpath('.//text()').getall()
    return " ".join("".join(texts).split())

def main():
    if not INPUT_HTML.exists():
        print(f"[!] Input file {INPUT_HTML} does not exist.")
        return

    with open(INPUT_HTML, 'r', encoding='utf-8') as f:
        html_content = f.read()

    page = Selector(html_content)
    job_cards = page.css('.job_seen_beacon')
    
    print(f"[*] Found {len(job_cards)} job cards. Parsing...")
    
    parsed_jobs = []
    
    for card in job_cards:
        job = {}
        
        # Link and ID
        title_link = card.css('.jcs-JobTitle')
        if title_link:
            job['id'] = title_link[0].attrib.get('data-jk', '')
            href = title_link[0].attrib.get('href', '')
            job['link'] = f"https://in.indeed.com{href}" if href else ''
            
            # Title text
            title_span = title_link[0].css('span[title]')
            if title_span:
                job['title'] = extract_text(title_span[0])
            else:
                job['title'] = extract_text(title_link[0])
                
        # Company
        company_elem = card.css('.company_location [data-testid="company-name"]')
        if company_elem:
            job['company'] = extract_text(company_elem[0])
            
        # Location
        location_elem = card.css('.company_location [data-testid="text-location"]')
        if location_elem:
            job['location'] = extract_text(location_elem[0])
            
        # Metadata (Pay, Job Type, etc.)
        metadata_elems = card.css('.metadataContainer li')
        metadata = []
        for el in metadata_elems:
            text = extract_text(el)
            if text:
                metadata.append(text)
        
        # Try to extract pay explicitly if it's in the metadata (usually contains a currency symbol or digits)
        pay_info = [m for m in metadata if any(char.isdigit() for char in m) and ('a year' in m or 'a month' in m or '₹' in m)]
        if pay_info:
            raw_pay = pay_info[0]
            job['pay'] = raw_pay
            metadata.remove(raw_pay)
            
        job['metadata'] = metadata
        
        # Description snippet
        snippet_elem = card.css('.job-snippet li')
        if snippet_elem:
            job['snippet'] = [extract_text(el) for el in snippet_elem if extract_text(el)]
            
        parsed_jobs.append(job)

    # Save to JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(parsed_jobs, f, indent=4, ensure_ascii=False)
        
    print(f"[OK] Parsed {len(parsed_jobs)} jobs and saved to {OUTPUT_JSON.resolve()}")

if __name__ == "__main__":
    main()
