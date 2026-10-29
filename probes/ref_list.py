import json
import os
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (research; local)'}
titles = [
    "File:Along the River During the Qingming Festival (Qing Court Version).jpg",
    "File:Along the River During the Qingming Festival (detail of original).jpg",
]
out_dir = r'J:\mickeylan\ai\blender\out\ref'
os.makedirs(out_dir, exist_ok=True)

for t in titles:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&titles="
           + urllib.parse.quote(t) +
           "&prop=imageinfo&iiprop=url|size&format=json")
    req = urllib.request.Request(api, headers=UA)
    d = json.load(urllib.request.urlopen(req, timeout=60))
    for p in d['query']['pages'].values():
        ii = p['imageinfo'][0]
        print("%-70s 原图 %sx%s  %.1f MB" % (
            p['title'], ii['width'], ii['height'], ii['size'] / 1e6))
        print("   ", ii['url'].split('?')[0])
