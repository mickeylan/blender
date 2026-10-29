import json
import os
import re
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (research; contact local)'}
API = ("https://commons.wikimedia.org/w/api.php?action=query&generator=categorymembers"
       "&gcmtitle=Category:Along%20the%20River%20During%20the%20Qingming%20Festival"
       "&gcmtype=file&gcmlimit=200&prop=imageinfo&iiprop=url|size&iiurlwidth=2000&format=json")

req = urllib.request.Request(API, headers=UA)
data = json.load(urllib.request.urlopen(req, timeout=60))
pages = data.get('query', {}).get('pages', {})
out_dir = r'J:\mickeylan\ai\blender\out\ref'
os.makedirs(out_dir, exist_ok=True)

items = []
for p in pages.values():
    ii = p.get('imageinfo', [{}])[0]
    items.append((p['title'], ii.get('thumburl') or ii.get('url'),
                  ii.get('thumbwidth'), ii.get('thumbheight')))
items.sort()
for t, u, w, h in items:
    print("%-70s %sx%s" % (t, w, h))
