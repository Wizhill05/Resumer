import json
from bs4 import BeautifulSoup

with open('src/job_organizer/sample.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), "lxml")

attr_nodes = soup.select("[data-testid='jobsearch-JobDescriptionSection-jobAttributes'] ul li, #jobDetailsSection .jobsearch-JobDescriptionSection-sectionItem")
if not attr_nodes:
    attr_nodes = soup.select(".jobsearch-JobDescriptionSection-sectionItem")

attributes = []
for node in attr_nodes:
    attributes.append(node.get_text(" ", strip=True))

print("Attributes:", attributes)
