"""Convert parsed tables (all.json) into compact app data (data.json)."""
import json, re, sys

src, out = sys.argv[1], sys.argv[2]
ts = json.load(open(src, encoding='utf-8'))


def clean(s):
    s = (s or '').replace('�', '')
    s = re.sub(r'(^|[\s(/])y\s*(\d)', r'\1≤ \2', s)
    s = re.sub(r'(^|[\s(/])u\s*(\d)', r'\1≥ \2', s)
    s = re.sub(r'\s*:\s*', ': ', s) if False else s
    return re.sub(r'\s+', ' ', s).strip()


def clean_volt(v):
    v = clean(v).replace('Ue: ', '').replace('Ue ', '')
    v = v.replace('220, 250 V DC', '220-250 V DC').replace('380-415 V Ph/Ph', '380-415 V AC Ph/Ph')
    if re.match(r'^4\d\d V AC$', v):
        v = '≤ ' + v
    return v


tables = []
for t in ts:
    volt = clean_volt(t['voltage'])
    tables.append(dict(
        id='p%d_%d' % (t['page'], t['tableIndex']),
        page=t['page'], ref=t['ref'],
        up=clean(t['up']), dn=clean(t['dn']), volt=volt, unit=t['unit'], ctx=clean(t['dnContext']),
        cols=[[clean(c['product']), clean(c['rating'])] for c in t['columns']],
        rows=[[clean(r['family']), clean(r['rating'])] for r in t['rows']],
        cells=[[(v or '') for v in row] for row in t['cells']],
    ))

# Fuse-fuse ratio table (A-143). Catalogue value "8000" for 1250 A is a typo for 800.
ff = [(16, 6, 4), (20, 10, 6), (25, 16, 8), (32, 20, 10), (40, 25, 12), (50, 32, 16), (63, 40, 20), (80, 50, 25),
      (100, 63, 32), (125, 80, 40), (160, 100, 63), (200, 125, 80), (250, 160, 125), (315, 200, 125), (400, 250, 160),
      (500, 315, 200), (630, 400, 250), (800, 500, 315), (1000, 630, 400), (1250, 800, 500)]
gG = sorted(set([2, 4, 6, 10, 16, 20, 25, 32, 35, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800]))
aM = sorted(set([2, 4, 6, 8, 10, 12, 16, 20, 25, 32, 40, 63, 80, 125, 160, 200, 250, 315, 400, 500]))
rows, cells = [], []
for kind, lst, idx in (('gG', gG, 1), ('aM', aM, 2)):
    for r in lst:
        rows.append(['Fupact %s fuse-link' % kind, str(r)])
        cells.append(['T' if r <= f[idx] else '' for f in ff])
tables.append(dict(
    id='p147_ff', page=147, ref='A-143', up='Fupact (gG fuse-link)', dn='Fupact (gG or aM fuse-link)',
    volt='Alle (IEC 60269)', unit='kA', ctx='', ratio=True,
    cols=[['Fupact gG fuse-link', 'In %d' % f[0]] for f in ff], rows=rows, cells=cells))

data = json.dumps(tables, ensure_ascii=False, separators=(',', ':'))
if out.endswith('.html'):
    tpl = open(sys.argv[3], encoding='utf-8').read()
    open(out, 'w', encoding='utf-8').write(tpl.replace('/*__DATA__*/null', data))
else:
    open(out, 'w', encoding='utf-8').write(data)
print(len(tables), 'tables')
