import urllib.parse
from scrapling.fetchers import StealthySession

def find_indeed_sc_codes():
    url = "https://in.indeed.com/jobs?q=ai+engineer&l=Bengaluru"
    
    with StealthySession(headless=True) as session:
        print("Fetching:", url)
        page = session.fetch(url, timeout=30000, google_search=False)
        if page.status != 200:
            print("Failed to fetch. Status:", page.status)
            return

        html = page.html_content
        
        # Look for filter links or JSON blobs that map job types to sc values.
        import re
        # Find all sc= values in the HTML
        sc_matches = re.findall(r'sc=([^"\'&]+)', html)
        decoded_scs = set(urllib.parse.unquote(sc) for sc in sc_matches)
        for sc in decoded_scs:
            print("Found SC param:", sc)
            
        print("---")
        # Also let's find the text around it to guess the job type
        # For example, look for "Full-time", "Internship", etc.
        for label in ["Full-time", "Part-time", "Internship", "Contract", "Temporary", "Fresher", "Permanent"]:
            # Find in html
            idx = html.find(label)
            if idx != -1:
                chunk = html[max(0, idx-200):idx+200]
                # Look for sc= inside this chunk
                m = re.search(r'sc=([^"\'&]+)', chunk)
                if m:
                    print(f"{label} -> {urllib.parse.unquote(m.group(1))}")
                else:
                    print(f"{label} -> Found text, but no SC near it.")
            else:
                print(f"{label} -> Not found in HTML")

if __name__ == "__main__":
    find_indeed_sc_codes()
