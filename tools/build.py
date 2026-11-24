"""Combine parsed tables into app data and inject into the HTML template.

Usage:
  python build.py new.json old.json index.html app_template.html

new.json : tables parsed from "Selektivitetstabeller 2026.pdf"  (primary source)
old.json : tables parsed from "Schneider - Selektivitetstabeller.pdf" (2019) - only iDPN tables
           that were dropped from the 2026 guide are kept from this file.
"""
import json, re, sys

new_src, old_src, out, tpl_path = sys.argv[1:5]


def clean(s):
    s = (s or '').replace('�', '').replace(' ', ' ')
    s = re.sub(r'(^|[\s(/])y\s*(\d)', r'\1≤ \2', s)
    s = re.sub(r'(^|[\s(/])u\s*(\d)', r'\1≥ \2', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_family(s):
    s = clean(s)
    s = re.sub(r'^stream\s+', '', s)
    s = re.sub(r'\s+Downstream$', '', s)
    s = s.replace('iiC40', 'iC40')
    return s


def clean_rating(s):
    s = clean(s)
    s = re.sub(r'Trip unit rating( In)?', 'In', s)
    s = s.replace('Rating (kA)', 'Rating').replace('CB Rating', 'Rating')
    return s


def clean_volt(v):
    v = clean(v)
    m = re.search(r'(≤\s*)?\d', v)            # drop "Ue:", section titles etc.
    v = v[m.start():] if m else v
    v = re.sub(r'(\d)V', r'\1 V', v)
    v = v.replace('220, 250 V DC', '220-250 V DC').replace('110, 125 V DC', '110-125 V DC')
    v = v.replace('380-415 V Ph/Ph', '380-415 V AC Ph/Ph')
    v = re.sub(r'\s*\[\d\]', '', v)
    if re.match(r'^4\d\d V AC$', v):
        v = '≤ ' + v
    return v


def convert(t, src):
    cols = [[clean(c['product']), clean_rating(c['rating'])] for c in t['columns']]
    rows = [[clean_family(r['family']), clean_rating(r['rating'])] for r in t['rows']]
    up = clean(t['up']).replace('iiC40', 'iC40') or (cols[0][0] if cols else '')
    dn = clean(t['dn']).replace('iiC40', 'iC40')
    if not dn:
        fams = list(dict.fromkeys(re.sub(r'\s*Curve [A-Z]$', '', r[0]) for r in rows))
        dn = ', '.join(fams[:3])
    return dict(
        id='%s_p%d_%d' % (src, t['page'], t['tableIndex']), src=src,
        page=t['page'], ref=t['ref'],
        up=up, dn=dn, volt=clean_volt(t['voltage']), unit=t['unit'], ctx=clean(t['dnContext']),
        cols=cols, rows=rows,
        cells=[[(v or '') for v in row] for row in t['cells']],
    )


tables = [convert(t, '2026') for t in json.load(open(new_src, encoding='utf-8'))]

# iDPN tables only exist in the 2019 catalogue
for t in json.load(open(old_src, encoding='utf-8')):
    if re.match(r'^\s*iDPN', t['dn'], re.I):
        keep = [i for i, r in enumerate(t['rows']) if 'idpn' in r['family'].lower()]
        if keep:
            t = dict(t, rows=[t['rows'][i] for i in keep], cells=[t['cells'][i] for i in keep])
            tables.append(convert(t, '2019'))

# Fuse-fuse ratio table (2026: A-181, 2019: A-143). Catalogue value "8000" for 1250 A is a typo for 800.
ff = [(16, 6, 4), (20, 10, 6), (25, 16, 8), (32, 20, 10), (40, 25, 12), (50, 32, 16), (63, 40, 20), (80, 50, 25),
      (100, 63, 32), (125, 80, 40), (160, 100, 63), (200, 125, 80), (250, 160, 125), (315, 200, 125), (400, 250, 160),
      (500, 315, 200), (630, 400, 250), (800, 500, 315), (1000, 630, 400), (1250, 800, 500)]
gG = [2, 4, 6, 10, 16, 20, 25, 32, 35, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800]
aM = [2, 4, 6, 8, 10, 12, 16, 20, 25, 32, 40, 63, 80, 125, 160, 200, 250, 315, 400, 500]
rows, cells = [], []
for kind, lst, idx in (('gG', gG, 1), ('aM', aM, 2)):
    for r in lst:
        rows.append(['FuPacT %s fuse-link' % kind, str(r)])
        cells.append(['T' if r <= f[idx] else '' for f in ff])
tables.append(dict(
    id='2026_ff', src='2026', page=189, ref='A-181', up='FuPacT (gG fuse-link)', dn='FuPacT (gG or aM fuse-link)',
    volt='Alle (IEC 60269)', unit='kA', ctx='', ratio=True,
    cols=[['FuPacT gG fuse-link', 'In %d' % f[0]] for f in ff], rows=rows, cells=cells))

data = json.dumps(tables, ensure_ascii=False, separators=(',', ':'))
tpl = open(tpl_path, encoding='utf-8').read()
open(out, 'w', encoding='utf-8').write(tpl.replace('/*__DATA__*/null', data))
print(len(tables), 'tables', '(2019-only:', sum(t['src'] == '2019' for t in tables), ')')
