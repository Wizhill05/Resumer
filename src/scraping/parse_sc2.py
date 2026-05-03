import urllib.request
import re
import urllib.parse

req = urllib.request.Request("https://in.indeed.com/jobs?q=ai+engineer&l=Bengaluru", headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    matches = re.findall(r'"label":"([^"]+)".*?"url":"([^"]+sc=0kf%3Aattr[^"]+)"', html)
    for label, url in matches:
        print(label)
        sc = re.search(r'sc=([^&]+)', url)
        if sc:
            print("  ", urllib.parse.unquote(sc.group(1)))
except Exception as e:
    print(e)
