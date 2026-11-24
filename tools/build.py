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


# ---------- motor protection rows (TeSys GV / LUB, Integral 63, iC60L MA / NG125L MA) ----------
# The catalogue writes these as "<code> <setting range>" in many variants: "01 0.1...0.16", "03 LRD3 0.25...0.40",
# "1.6 LRD6 1...1.6" (MA rating + thermal relay), "100 kA LRD 03 0.25/0.40" (690 V), "LB1-LD03M16 10-13" ...
# They are turned into one label per device, identical in every table:  "0,25–0,4 A · 03 + LRD03".
MOTOR = re.compile(r'^(TeSys |Integral 63|iC60L MA|NG125L MA)')
# known misprints in the 2026 guide (setting ranges confirmed by the other tables / the product range)
MOTOR_FIX = {('TeSys GV3', '13'): (9, 13), ('Integral 63', 'LB1-LD03M16'): (10, 13)}


def dk(x):
    return ('%g' % x).replace('.', ',')


def range_relay(s):
    """'03 LRD3 0.25...0.40' -> (0.25, 0.4, 'LRD03', '03'); None when there is no setting range."""
    found = list(re.finditer(r'(\d+(?:[.,]\d+)?)\s*(?:\.\.\.|/|-)\s*(\d+(?:[.,]\d+)?)', s))
    if not found:
        return None
    last = found[-1]
    head = s[:last.start()].strip()
    # thermal relay: LRD6, LRD 03, LRD-07, LRD3355, LRD 33 55, LRD-33 63, LR9D-5369 ...
    relay = re.search(r'LR[0-9A-Z]*(?:[\s-]*\d+(?![\d.,/]))*', head)
    rl = ''
    if relay:
        rl = re.sub(r'[\s-]', '', relay.group(0))
        rl = re.sub(r'^LRD(\d)$', r'LRD0\1', rl)
        rl = 'LR9' if rl.startswith('LR9') else rl   # LR9D5369 / LR9-F5369 / LR9/F-5369: written differently per table
        head = (head[:relay.start()] + head[relay.end():]).strip()
    return num(last.group(1)), num(last.group(2)), rl, head


def motor(fam, rating, k):
    """-> (k with udførelse filled in, label or '' for a row that covers all sizes)."""
    s = re.sub(r'\.{2,}|…', '...', clean(rating))
    s = re.sub(r'\b\d+\s*kA\b|Integrated', ' ', s).strip()
    series = k[0][0]
    # udførelse from the device name: GV2 ME01 / GV2 L03 / GV3 P13 / GV4 P/PE/PEM ...
    gv = re.search(r'GV\d\s?(ME|PEM|PE|P|LE|L)\s?(\d{2,3})', fam)
    if gv and series.startswith('TeSys GV') and not k[0][1]:
        k = [[x[0], [gv.group(1)], x[2]] for x in k]
    g56 = re.search(r'GV([56])\s?P\s?(\d{3})', fam)
    if g56:
        return k, '%s A · GV%sP%s' % (g56.group(2), g56.group(1), g56.group(2))
    parts = range_relay(s)
    if not parts:
        return k, ''                                 # summary row ("GV2 ME01...ME32") = all sizes
    lo, hi, rl, head = parts
    tok = head.split()[0] if head.split() else ''
    if series.endswith(' MA'):
        ref = 'MA' + dk(num(tok)) if re.fullmatch(r'\d+(?:[.,]\d+)?', tok) else ''
    elif series == 'Integral 63':
        ref = tok
    elif series.startswith('TeSys U'):
        code = re.sub(r'^LUC\W*', '', tok) or re.sub(r'.*LUC\W*', '', fam)
        if not re.fullmatch(r'X6|1X|\d{2}', code):
            return k, ''                             # "LUB12 + LUC• 6...12" = all sizes
        ref = 'LUC•' + code
    else:
        ref = tok if re.fullmatch(r'\d{2,3}', tok) else (gv.group(2) if gv else tok)
    if (series, ref) in MOTOR_FIX:
        lo, hi = MOTOR_FIX[(series, ref)]
    ref = ' + '.join(x for x in (ref, rl) if x)
    return k, '%s–%s A' % (dk(lo), dk(hi)) + (' · ' + ref if ref else '')


# ---------- MasterPacT MTZ / ComPacT NS as downstream device ----------
# The frame ("MTZ1 06", "NS800") is written either in the device column ("MTZ1 06 H1/H2 MicroLogic X" + trip unit
# rating "400") or in the rating column ("MasterPacT MTZ1 H1 MicroLogic" + "MTZ1 06"). The frame becomes the
# Mærkestrøm choice ("630 A · MTZ1 06") and the trip unit rating the Indstilling choice ("Udløser 400 A").
FRAME_A = {'06': 630, '08': 800, '10': 1000, '12': 1250, '16': 1600, '20': 2000, '25': 2500, '32': 3200,
           '40': 4000, '40b': 4000, '50': 5000, '63': 6300}


def frame_label(text):
    m = re.search(r'MTZ\s?([123])\s?(\d{2}b?)(?!\s*[-–/]\s*\d)', text)
    if m and m.group(2) in FRAME_A:
        return '%d A · MTZ%s %s' % (FRAME_A[m.group(2)], m.group(1), m.group(2))
    m = re.search(r'(?<!X)\bNS\s?(\d{3,4})(\s?b)?(?!\d|\s*[-–]\s*\d)', text)
    if m:
        return '%s A · NS%s%s' % (m.group(1), m.group(1), 'b' if m.group(2) else '')
    return None


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
    fams = [re.sub(r'^stream\s+|\s+Downstream$', '', clean(r['family'])).replace('iiC40', 'iC40') for r in t['rows']]
    # NSX motor rows printed over two lines: "NSX100 F/N/H/S/" + "L/R", "NSX100" + "F/N/H/S/L/R" -> one name for both
    for i in range(1, len(fams)):
        if re.match(r'^(?:ComPacT\s*)?NSX\d{3}', fams[i - 1]) and \
                re.fullmatch(r'[A-Z]{1,2}(?:\s*/\s*[A-Z]{1,2})*/?|MicroLogic.*', fams[i]):
            whole = fams[i - 1] + ('' if fams[i - 1].endswith('/') else ' ') + fams[i]
            fams[i - 1] = fams[i] = whole
    prev_rating = ''
    for r, fam in zip(t['rows'], fams):
        rating = r['rating'] or ''
        mic = re.match(r'^(?:Mic\.?\s*2\.2M|or\s*6\.2E?M)\s*', rating)
        if mic:                                   # "Mic. 2.2M 25...50" / "or 6.2EM 100 (80)"
            fam, rating = fam + ' MicroLogic 2.2M/6.2M', rating[mic.end():]
        vals, ir, lab = dn_rating(re.sub(r'\s*(?:\.{2,}|…)\s*', '-', rating) if mic else rating)
        amps = max([num(v) for v in vals] or [0]) if vals else None
        # frame size written in the rating column ("ComPacT B/F/H/N/S/L/R TM-D" + "NSX100", "ComPacT NS H" + "NS1600b"):
        # the device is <frame> + <performance / trip unit>, and the row covers every rating of that frame
        size = re.fullmatch(r'\s*(?:Com[Pp]ac[Tt]\s*)?(NSX\s?\d{3}|NS\s?\d{3,4}\s?b?)\s*(.*)', rating)
        if size:
            rest = re.sub(r'\bCom[Pp]ac[Tt]\b|\bNSX?\b(?!\s?\d)', ' ', fam)
            k = keys(size.group(1) + ' ' + size.group(2) + ' ' + rest, dn_title)
            ns = re.fullmatch(r'NS\s?(\d{3,4})\s?b?', size.group(1))
            # NS630b-1600 / NS1600b-3200 are one series each: keep the frame as its In; NSX frames are own series
            vals, lab = ([ns.group(1)], ns.group(1)) if ns else (None, '')
        else:
            k = keys(fam, dn_title, amps)
        vals = limit(vals, k, rating)
        if k and all(MOTOR.match(x[0]) for x in k):
            k, mlab = motor(fam, rating, k)
            vals, ir, lab = ([mlab], '', mlab) if mlab else (None, '', '')
        elif k and all(x[0].startswith('ComPacT NSX') for x in k):
            # NSX + MA trip unit + thermal relay: "MA2.5 LRD6 1...1.6", "NSX100 L MA 2.5" + "LRD 06 1/1.6"
            ma = re.search(r'\bMA\s?(\d+(?:[.,]\d+)?)', fam + ' ' + rating)
            parts = range_relay(re.sub(r'\.{2,}|…', '...', clean(rating))) if ma else None
            if parts and parts[2]:
                mlab = '%s–%s A · MA%s + %s' % (dk(parts[0]), dk(parts[1]), dk(num(ma.group(1))), parts[2])
                k = [[x[0], x[1], ['MA']] for x in k]
                vals, ir, lab = [mlab], '', mlab
        elif k and all(re.match(r'MasterPacT MTZ|ComPacT NS(?!X)', x[0]) for x in k):
            rt = prev_rating if rating.strip() in ('LB', 'L/LB') else rating   # "NS630bL/" + "LB" on two lines
            fr = frame_label(rt) if re.match(r'\s*(?:Com[Pp]ac[Tt]\s*)?(?:MTZ|NS)', rt) else None
            if fr:
                vals, ir, lab = [fr], '', fr
            else:
                fr, n = frame_label(fam), re.fullmatch(r'\s*([≤≥]\s*)?(\d+)\s*', rating)
                if fr and n:
                    vals, ir, lab = [fr], 'Udløser %s%s A' % (n.group(1) or '', n.group(2)), fr
        prev_rating = rating
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
        vals = expand(rating, k)
        if k and all(MOTOR.match(x[0]) for x in k):   # same device labels as the ordinary tables
            k, mlab = motor(fam, clean(r['trip'] + ' ' + rating), k)
            vals = [mlab] if mlab else None
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
    # motor rows: use the exact label of the ordinary tables (same series/udførelse and setting range), so the
    # cascading lookup finds the device the user picked ("0,25–0,4 A · 03 + LRD03" also when casc says LR2 D13 03)
    known = {}
    for t in tables:
        for r in t['rows']:
            for k in r['k']:
                if MOTOR.match(k[0]) and r['v']:
                    for p in (k[1] or ['']):
                        known.setdefault((k[0], p, r['v'][0].split(' · ')[0]), r['v'][0])
    for t in casc:
        for r in t['rows']:
            if r['v'] and all(MOTOR.match(k[0]) for k in r['k']):
                rng = r['v'][0].split(' · ')[0]
                hit = [known.get((k[0], p, rng)) for k in r['k'] for p in (k[1] or [''])]
                ref = r['v'][0].split(' · ')[1] if ' · ' in r['v'][0] else None
                hit = [h for h in hit if h] or \
                    [v for (s, _, x), v in known.items() if s == r['k'][0][0] and (x == rng or ref and v.endswith(' · ' + ref))]
                if hit:
                    r['v'] = [hit[0]]

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
