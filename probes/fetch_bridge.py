import json
import os
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (research; local)'}
API = ("https://commons.wikimedia.org/w/api.php?action=query&titles=File:Alongtheriver%20BridgeDetail.jpg"
       "&prop=imageinfo&iiprop=url&iiurlwidth=2200&format=json")

req = urllib.request.Request(API, headers=UA)
data = json.load(urllib.request.urlopen(req, timeout=60))
out = r'J:\mickeylan\ai\blender\out\ref\bridge_detail.jpg'
os.makedirs(os.path.dirname(out), exist_ok=True)
url = None
for p in data['query']['pages'].values():
    ii = p['imageinfo'][0]
    url = ii.get('thumburl') or ii['url']
    print("标题:", p['title'])
    print("URL:", url)
if url:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data_b = r.read()
    open(out, 'wb').write(data_b)
    print("已保存", out, len(data_b), "bytes")
