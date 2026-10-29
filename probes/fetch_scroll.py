import os
import urllib.request
from PIL import Image

UA = {'User-Agent': 'Mozilla/5.0 (research; local)'}
URL = ("https://upload.wikimedia.org/wikipedia/commons/4/43/"
       "Along_the_River_During_the_Qingming_Festival_%28detail_of_original%29.jpg")
out_dir = r'J:\mickeylan\ai\blender\out\ref'
os.makedirs(out_dir, exist_ok=True)
p = os.path.join(out_dir, 'scroll_detail.jpg')
if not os.path.exists(p):
    with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=180) as r:
        open(p, 'wb').write(r.read())
im = Image.open(p)
print("下载:", p, im.size)
