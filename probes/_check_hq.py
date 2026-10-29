import ast

p = r'J:\mickeylan\ai\blender\ai_loop.py'
s = open(p, encoding='utf-8').read()
ast.parse(s)
print('syntax OK')
i = s.index('def hongqiao')
j = s.index('# ================= 形制助手：反曲屋顶 =================')
blk = s[i:j]
for n, l in enumerate(blk.split('\n')):
    if 'def profile' in l or '横梁贯穿' in l or 'HONGQIAO' in l:
        print(n, l.strip()[:70])
