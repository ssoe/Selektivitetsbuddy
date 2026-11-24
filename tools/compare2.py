"""Match every 2026 table to its most similar 2019 table (same voltage class + same grid shape) and report differences."""
import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')
old = json.load(open(sys.argv[1], encoding='utf-8'))
new = json.load(open(sys.argv[2], encoding='utf-8'))


def nv(v):
    v = v.lower()
    for k, tag in (('690', '690'), ('24-48', 'dc24'), ('110', 'dc110'), ('220-250', 'dc220'), ('220, 250', 'dc220'), ('440', '440')):
        if k in v: return tag
    return 'ac400'


def grid(t):
    return [[(v or '').rstrip('*') for v in r] for r in t['cells']]


def rnums(t):
    return [tuple(re.findall(r'\d+(?:\.\d+)?', r['rating'])) for r in t['rows']]


res = {'same': [], 'changed': [], 'new': []}
used = set()
for y in new:
    gy = grid(y)
    best, bscore = None, 0
    for i, x in enumerate(old):
        if nv(x['voltage']) != nv(y['voltage']): continue
        gx = grid(x)
        if len(gx) == len(gy) and all(len(a) == len(b) for a, b in zip(gx, gy)):
            n = sum(len(r) for r in gy) or 1
            eq = sum(a == b for ra, rb in zip(gx, gy) for a, b in zip(ra, rb)) / n
            if eq > bscore: best, bscore = i, eq
        elif len(gx[0] if gx else []) == len(gy[0] if gy else []) and rnums(x)[:5] == rnums(y)[:5] and y['up'][:6].lower() == x['up'][:6].lower():
            if 0.5 > bscore: best, bscore = i, 0.5
    if best is None or bscore < 0.5:
        res['new'].append(y); continue
    x = old[best]; used.add(best)
    gx = grid(x)
    if len(gx) == len(gy) and all(len(a) == len(b) for a, b in zip(gx, gy)):
        d = [(ri, ci, gx[ri][ci], gy[ri][ci]) for ri in range(len(gy)) for ci in range(len(gy[ri])) if gx[ri][ci] != gy[ri][ci]]
    else:
        d = None
    if d == []:
        res['same'].append((x, y))
    else:
        res['changed'].append((x, y, d))

print('UÆNDREDE:', len(res['same']))
print('ÆNDREDE:', len(res['changed']))
for x, y, d in res['changed']:
    if d is None:
        print(f"  {y['ref']} (gl. {x['ref']}) {y['up']} → {y['dn']}: struktur ændret {len(x['cells'])}→{len(y['cells'])} rækker")
        continue
    up = sum(1 for _, _, a, b in d if (b == 'T' and a != 'T') or (a and b and a != 'T' and b != 'T' and float(b) > float(a)) or (not a and b))
    dn = len(d) - up
    ex = '; '.join(f"{y['rows'][ri]['family'][:22]} {y['rows'][ri]['rating']} / {y['columns'][ci]['rating'][-14:]}: {a or '–'}→{b or '–'}" for ri, ci, a, b in d[:3])
    print(f"  {y['ref']} (gl. {x['ref']}) {y['up']} → {y['dn']} [{y['voltage']}]: {len(d)} celler (bedre {up}, dårligere {dn}). Fx {ex}")
print('NYE (ingen tilsvarende 2019-tabel):', len(res['new']))
for y in res['new']:
    print(f"  {y['ref']} {y['up']} → {y['dn']} [{y['voltage']}]")
print('2019-TABELLER UDEN MATCH:', len(old) - len(used))
for i, x in enumerate(old):
    if i not in used:
        print(f"  {x['ref']} {x['up']} → {x['dn']} [{x['voltage']}]")
