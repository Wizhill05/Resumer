from scrapling.fetchers import StealthySession
from scrapling.parser import Selector

def extract_text(element) -> str:
    if not element:
        return ""
    texts = element[0].xpath(".//text()").getall()
    return " ".join("".join(texts).split())

with StealthySession(headless=True) as s:
    p = s.fetch('https://in.indeed.com/viewjob?jk=7166aaae64ad1ccf', google_search=False)
    sel = Selector(p.html_content)
    
    title = extract_text(sel.css('h1'))
    company = extract_text(sel.css('[data-testid="inlineHeader-companyName"]'))
    loc = extract_text(sel.css('[data-testid="inlineHeader-companyLocation"]'))
    pay = extract_text(sel.css('#salaryInfoAndJobType'))
    
    print("Title:", title)
    print("Company:", company)
    print("Loc:", loc)
    print("Pay:", pay)
