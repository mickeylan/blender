import json
import os
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (research; local)'}
TITLE = "File:Rainbow Bridge in Millennium City Park 20180120.jpg"
api = ("https://commons.wikimedia.org/w/api.php?action=query&titles="
       + urllib.parse.quote(TITLE) +
       "&prop=imageinfo&iiprop=url|size&iiurlwidth=2400&format=json")
d = json.load(urllib.request.urlopen(urllib.request.Request(api, headers=UA),
                                      timeout=60))
out_dir = r'J:\mickeylan\ai\blender\out\ref'
os.makedirs(out_dir, exist_ok=True)
for p in d['query']['pages'].values():
    ii = p['imageinfo'][0]
    url = ii.get('thumburl') or ii['url']
    print(p['title'], ii['width'], ii['height'])
    print(url)
    out = os.path.join(out_dir, 'rainbow_park.jpg')
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=180) as r:
        open(out, 'wb').write(r.read())
    print("已保存", out)
