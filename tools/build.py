"""Combine parsed tables into normalised app data and inject it into the HTML template.

Usage:
  python build.py new.json old.json index.html app_template.html

new.json : tables parsed from "Selektivitetstabeller 2026.pdf"  (primary source)
old.json : tables parsed from "Schneider - Selektivitetstabeller.pdf" (2019) - only the iDPN rows,
           which were dropped from the 2026 guide, are kept from this file.

Every column (upstream device) and row (downstream device) is normalised with normalize.py into
  k  : list of [series, [udførelser], [udløsere]]
  In : rated current (upstream) / v : list of In values the row covers (downstream)
so the app can offer serie -> udførelse -> udløser -> In -> indstilling instead of raw labels.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize import series, trips, up_rating, dn_rating, NSX_SIZES  # noqa: E402

new_src, old_src, out, tpl_path = sys.argv[1:5]
casc_src = sys.argv[5] if len(sys.argv) > 5 else None


def clean(s):
    s = (s or '').replace('�', '').replace(' ', ' ')
    s = re.sub(r'(^|[\s(/])y\s*(\d)', r'\1≤ \2', s)
    s = re.sub(r'(^|[\s(/])u\s*(\d)', r'\1≥ \2', s)
    s = re.sub(r'\[\s*\d+\s*\]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_volt(v):
    v = clean(v)
    m = re.search(r'(≤\s*)?\d', v)
    v = v[m.start():] if m else v
    v = re.sub(r'(\d)V', r'\1 V', v)
    v = v.replace('220, 250 V DC', '220-250 V DC').replace('110, 125 V DC', '110-125 V DC')
    v = v.replace('380-415 V Ph/Ph', '380-415 V AC Ph/Ph')
    if re.match(r'^4\d\d V AC$', v):
        v = '≤ ' + v
    return v


def recognised(sl):
    return [s for s in sl if not re.match(r'^[^A-Za-z]*$|^[A-Z/ ]{1,20}( MicroLogic| TM-D.*)?$|^\(|^\d|^All|^TM-|^Micro', s[0])]


def nsx_fix(sl, amps):
    """Generic 'ComPacT NSX' -> size from current; multi-size columns -> drop sizes smaller than the current."""
    out = []
    for name, perfs in sl:
        if name == 'ComPacT NSX' and amps:
            size = next((n for n in NSX_SIZES if n >= amps), None)
            if size:
                name = 'ComPacT NSX%d' % size
        m = re.match(r'ComPacT NSX(\d+)$', name)
        if m and amps and int(m.group(1)) < amps:
            continue
        if not any(o[0] == name for o in out):
            out.append((name, perfs))
    if any(re.match(r'ComPacT NSX\d', n) for n, _ in out):
        out = [o for o in out if o[0] != 'ComPacT NSX']
    return out or sl


def keys(label, fallback_title, amps=None):
    sl = recognised(series(label))
    if not sl:
        fb = recognised(series(fallback_title))
        # keep perf letters written in the row label itself
        letters = [x for x in re.findall(r'(?<![A-Za-z])[A-Z][A-Z0-9]?(?![a-z])', clean(label))]
        sl = [(n, [p for p in letters if p in ('N', 'H', 'L', 'LB', 'B', 'F', 'S', 'R', 'E', 'N1', 'H1', 'H2', 'H3', 'L1')] or perfs)
              for n, perfs in fb]
    if not sl:
        sl = [(clean(label) or clean(fallback_title), [])]
    sl = nsx_fix(sl, amps)
    tr = trips(label)
    if tr == [''] and len(recognised(series(fallback_title))) <= 1:
        tr = trips(fallback_title) if fallback_title and not re.search(r'curves', fallback_title, re.I) else tr
    return [[n, p, tr] for n, p in sl]


def num(x):
    try:
        return float(str(x).replace(',', '.'))
    except (TypeError, ValueError):
        return None


# realistic In range per series - used to bound "≤ x" / "≥ x" / range expansions
RANGE = [(r'^ComPacT NSXm', 16, 160), (r'^ComPacT NSX100', 16, 100), (r'^ComPacT NSX160', 16, 160),
         (r'^ComPacT NSX250', 16, 250), (r'^ComPacT NSX400', 160, 400), (r'^ComPacT NSX630', 250, 630),
         (r'^ComPacT NS630', 250, 1600), (r'^ComPacT NS1600', 1600, 3200), (r'^MasterPacT', 250, 6300),
         (r'^iC40|^iCV|^iDPN', 0.5, 40), (r'^iC60', 0.5, 63), (r'^C120|^NG125', 10, 125)]


def limit(vals, k, raw):
    """Drop expanded values outside the series' realistic range (exact values are always kept)."""
    if not vals or re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*(\(\w+\))?\s*', raw or ''):
        return vals
    for rx, lo, hi in RANGE:
        if k and all(re.match(rx, x[0]) for x in k):
            return [v for v in vals if lo <= num(v) <= hi] or vals
    return vals


def convert(t, src):
    up_title, dn_title = clean(t['up']), clean(t['dn'])
    cols = []
    prev = {}
    for c in t['columns']:
        In, st = up_rating(c['rating'])
        prod = clean(c['product'])
        if In is None and prod in prev:          # rating spanned from the column to the left
            In = prev[prod]
        if In is not None:
            prev[prod] = In
        cols.append(dict(k=keys(prod, up_title, num(In)), In=In or '', st=st,
                         raw=(prod + ' · ' + clean(c['rating'])).strip(' ·')))
    rows = []
    for r in t['rows']:
        vals, ir, lab = dn_rating(r['rating'])
        fam = re.sub(r'^stream\s+|\s+Downstream$', '', clean(r['family'])).replace('iiC40', 'iC40')
        amps = max([num(v) for v in vals] or [0]) if vals else None
        k = keys(fam, dn_title, amps)
        size = re.fullmatch(r'\s*(?:ComPacT\s*)?NSX\s?(\d{3})\s*', r['rating'] or '')
        if size and any(x[0] == 'ComPacT NSX' for x in k):   # frame size written in the rating column
            k = [['ComPacT NSX' + size.group(1) if x[0] == 'ComPacT NSX' else x[0], x[1], x[2]] for x in k]
            vals, lab = None, ''
        vals = limit(vals, k, r['rating'])
        rows.append(dict(k=k, v=vals, ir=ir, lab=lab,
                         raw=(fam + (' · ' + clean(r['rating']) if r['rating'] else '')).strip()))
    return dict(id='%s_p%d_%d' % (src, t['page'], t['tableIndex']), src=src, page=t['page'], ref=t['ref'],
                up=up_title.replace('iiC40', 'iC40'), dn=dn_title.replace('iiC40', 'iC40'),
                volt=clean_volt(t['voltage']), unit=t['unit'], ctx=clean(t['dnContext']),
                cols=cols, rows=rows, cells=[[(v or '') for v in row] for row in t['cells']])


tables = [convert(t, '2026') for t in json.load(open(new_src, encoding='utf-8'))]

# iDPN rows only exist in the 2019 catalogue
for t in json.load(open(old_src, encoding='utf-8')):
    if re.match(r'^\s*iDPN', t['dn'], re.I):
        keep = [i for i, r in enumerate(t['rows']) if 'idpn' in r['family'].lower()]
        if keep:
            t = dict(t, rows=[t['rows'][i] for i in keep], cells=[t['cells'][i] for i in keep])
            tables.append(convert(t, '2019'))

# Fuse-fuse ratio table (2026: A-181). Catalogue value "8000" for 1250 A is a typo for 800.
ff = [(16, 6, 4), (20, 10, 6), (25, 16, 8), (32, 20, 10), (40, 25, 12), (50, 32, 16), (63, 40, 20), (80, 50, 25),
      (100, 63, 32), (125, 80, 40), (160, 100, 63), (200, 125, 80), (250, 160, 125), (315, 200, 125), (400, 250, 160),
      (500, 315, 200), (630, 400, 250), (800, 500, 315), (1000, 630, 400), (1250, 800, 500)]
gG = [2, 4, 6, 10, 16, 20, 25, 32, 35, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800]
aM = [2, 4, 6, 8, 10, 12, 16, 20, 25, 32, 40, 63, 80, 125, 160, 200, 250, 315, 400, 500]
rows, cells = [], []
for kind, lst, idx in (('gG', gG, 1), ('aM', aM, 2)):
    for r in lst:
        rows.append(dict(k=[['%s-sikring' % kind, [], ['']]], v=[str(r)], ir='', lab=str(r), raw='FuPacT %s %d A' % (kind, r)))
        cells.append(['T' if r <= f[idx] else '' for f in ff])
tables.append(dict(
    id='2026_ff', src='2026', page=189, ref='A-181', up='FuPacT (gG fuse-link)', dn='FuPacT (gG or aM fuse-link)',
    volt='Alle (IEC 60269)', unit='kA', ctx='', ratio=True,
    cols=[dict(k=[['gG-sikring', [], ['']]], In=str(f[0]), st='', raw='FuPacT gG %d A' % f[0]) for f in ff],
    rows=rows, cells=cells))


# ---------- "Selectivity enhanced by cascading" (2026: A-216 - A-245), parsed by parse_casc.py ----------
def expand(rating, k):
    """'≤ 100' / '125-160' / '80/100' / '40' -> list of In values (strings) bounded by the series range."""
    r = clean(rating).replace('A', '').strip()
    if not r:
        return None
    if re.fullmatch(r'\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)+', r):      # 80/100, 40/50
        vals = [fmt_num(num(x)) for x in r.split('/')]
    else:
        vals, _, _ = dn_rating(r.replace(' to ', '-'))
    return limit(vals, k, r) if vals else None


def fmt_num(n):
    return ('%g' % n).replace('.', ',')


def casc_volt(v):
    v = clean(v).replace('Ue:', '').strip()
    m = re.search(r'\d[\d\-/ ]*V(?: AC)?', v)
    return m.group(0).strip() if m else v


def convert_casc(t):
    up_title, dn_title = clean(t['up']), clean(t['dn'])
    cols = []
    for c in t['columns']:
        rating, setting = c['rating'], c['setting']
        if not rating and setting:                 # TM-D tables: the "Setting Ir" row is the rating
            rating, setting = setting, ''
        prod = clean(c['product'] + ' ' + c['trip'])
        k = keys(prod, up_title)
        ins = expand(rating, k)
        k = keys(prod, up_title, max(num(x) for x in ins) if ins else None)
        cols.append(dict(k=k, In=ins or [], inl=clean(rating), ir=('Ir ' + clean(setting)) if setting else '',
                         icu=clean(c['icu']).replace(' kA', '').replace(' ', ''),
                         raw=' · '.join(x for x in (clean(c['product']), c['trip'] and clean(c['trip']),
                                                     ('In ' + clean(rating)) if rating else '',
                                                     ('Ir ' + clean(setting)) if setting else '',
                                                     ('Icu ' + clean(c['icu']).replace(' kA', '') + ' kA') if c['icu'] else '') if x)))
    rows = []
    for r in t['rows']:
        fam = clean(r['family'])
        rating = r['rating']
        if rating and rating == r['icu'] and not re.search(r'\d', fam.split()[-1]):
            rating = ''                            # stray Icu value printed in the rating column
        label = fam + (' ' + clean(r['trip']) if r['trip'] else '')
        k = keys(label, dn_title)
        gv = re.match(r'GV\d\s?(ME|PE|P|LE|L)\d', fam)      # GV2 ME01 / GV2 P01 / GV2 L03 -> udførelse
        if gv:
            k = [[x[0], [gv.group(1)], x[2]] if x[0].startswith('TeSys GV') else x for x in k]
        vals = expand(rating, k)
        rng = [num(x) for x in re.findall(r'\d+(?:[.,]\d+)?', clean(rating))] if rating else []
        rows.append(dict(k=k, v=vals, rng=rng if len(rng) == 2 and '-' in rating else [], lab=clean(rating),
                         icu=clean(r['icu']), icn=clean(r['icn']),
                         raw=' · '.join(x for x in (label, ('In ' + clean(rating)) if rating else '',
                                                     ('Icu ' + clean(r['icu']) + ' kA') if r['icu'] else '',
                                                     ('Icn ' + clean(r['icn'])) if r['icn'] else '') if x)))
    return dict(id='casc_p%d_%d' % (t['page'], t['tableIndex']), page=t['page'], ref=t['ref'],
                up=up_title, dn=dn_title, volt=casc_volt(t['voltage']), cols=cols, rows=rows,
                cells=[[(v or '') for v in row] for row in t['cells']])


casc = []
if casc_src:
    casc = [convert_casc(t) for t in json.load(open(casc_src, encoding='utf-8'))]

data = json.dumps(tables, ensure_ascii=False, separators=(',', ':'))
cdata = json.dumps(casc, ensure_ascii=False, separators=(',', ':'))
tpl = open(tpl_path, encoding='utf-8').read()
app = open(os.path.join(os.path.dirname(os.path.abspath(tpl_path)), 'app.js'), encoding='utf-8').read()
html = tpl.replace('<script src="app.js"></script>',
                   '<script>\nconst DATA = ' + data + ';\nconst CASC = ' + cdata + ';\n' + app + '\n</script>')
assert html != tpl, 'script placeholder not found in template'
open(out, 'w', encoding='utf-8').write(html)

# summary for review
up_series = sorted({k[0] for t in tables for c in t['cols'] for k in c['k']})
dn_series = sorted({k[0] for t in tables for r in t['rows'] for k in r['k']})
print(len(tables), 'tables (2019-only:', sum(t['src'] == '2019' for t in tables), ')')
print(len(casc), 'cascading tables, series up:', sorted({k[0] for t in casc for c in t['cols'] for k in c['k']}),
      'down:', sorted({k[0] for t in casc for r in t['rows'] for k in r['k']}))
print('upstream series (%d):' % len(up_series), ' | '.join(up_series))
print('downstream series (%d):' % len(dn_series), ' | '.join(dn_series))
