import re
from scrapling.parser import Selector

with open('src/scraping/output/job_details_raw.html', 'r', encoding='utf-8') as f:
    html = f.read()

page = Selector(html)
desc = page.css('#jobDescriptionText')
if desc:
    texts = desc[0].xpath('.//text()').getall()
    print('Description length:', len(' '.join(''.join(texts).split())))

pattern = re.compile(r'"__typename":"JobAttribute","key":"[^"]+","label":"([^"]+)"')
matches = pattern.findall(html)
print('Attributes:', set(matches))
