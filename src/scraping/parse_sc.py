import json, re

try:
    with open("indeed_initial_data.json", encoding="utf-8") as f:
        data = f.read()
        
    # Look for "label":"Internship","url":"/jobs?..."
    matches = re.findall(r'"label":"([^"]+)".*?"url":"([^"]+)"', data)
    
    # Filter for jobs?q=
    filter_urls = [(label, url) for label, url in matches if "/jobs?" in url]
    
    for label, url in filter_urls:
        if label in ["Full-time", "Part-time", "Internship", "Contract", "Temporary", "Fresher", "Permanent"]:
            print(f"{label}: {url}")
            # Try to extract sc=
            m = re.search(r'sc=([^&]+)', url)
            if m:
                print(f"  SC: {m.group(1)}")
                
except Exception as e:
    print(e)
