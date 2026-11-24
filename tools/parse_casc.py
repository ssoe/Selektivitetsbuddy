"""Parse the "Selectivity enhanced by cascading" tables (2026 guide, PDF pages 224-253).

Usage:
  python parse_casc.py "Selektivitetstabeller 2026.pdf" casc.json [pages]     (default pages 224-253)

These tables have a fixed grid that differs from the ordinary selectivity tables:
  upstream header rows   : product / performance letters / Icu (kA) / Trip unit / Rating (A) / Setting Ir (A)
  downstream left columns: CB type (family) / Rating or In (A) / Icu (kA) / Trip unit / Icn (A) ...
  cells                  : "selectivity limit / breaking capacity enhanced by cascading", e.g. 16/25, -/20

Output per table: {page, ref, tableIndex, up, dn, voltage,
                   columns: [{product, icu, trip, rating, setting}],
                   rows: [{family, rating, icu, trip, icn}], cells: [[str|None]]}
"""
import json
import re
import sys

import pymupdf

PDF, OUT = sys.argv[1], sys.argv[2]
PAGES = sys.argv[3] if len(sys.argv) > 3 else '224-253'

CELL_RE = re.compile(r'^(\d+(?:[.,]\d+)?|[-—–])\s*/\s*\d+(?:[.,]\d+)?\*?$')
# text in the family column that starts a new downstream device (anything else continues the previous one)
DEVICE_RE = re.compile(r'^(i?C60|iC40|iCV|C120|NG125|NSX|NS\s?\d|ComPacT|LUB|GV\d|Integral|iDPN|MTZ|MasterPacT)', re.I)
LEGEND_RE = re.compile(r'^(Downstream device|breaking capacity|by cascading|Selectivity limit enhanced|\(in kA\)|Note:|VD:)')
DN_LABELS = re.compile(r'^(CB type|Rating|In \(A\)|In$|Icu|Icn|Trip unit|Thermal|relay|type)', re.I)


def spans_of(page):
    """Text spans, split where the PDF glued a label and a value together ("Setting Ir (A) 63")."""
    out = []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                chars = s['chars']
                groups, cur = [], []
                for i, ch in enumerate(chars):
                    c = ch['c']
                    w = ch['bbox'][2] - ch['bbox'][0]
                    gap = ch['bbox'][0] - chars[i - 1]['bbox'][2] if i else 0
                    if (c == ' ' and w > 4) or gap > 2.5:
                        if cur:
                            groups.append(cur)
                        cur = [] if c == ' ' else [ch]
                    else:
                        cur.append(ch)
                if cur:
                    groups.append(cur)
                for g in groups:
                    t = ''.join(ch['c'] for ch in g).replace('\xa0', ' ').replace('�', '').strip()
                    if not t or re.fullmatch(r'\[\s*\d+\s*\]|\(\d\)', t):   # footnote markers
                        continue
                    x0 = min(ch['bbox'][0] for ch in g if ch['c'].strip()) if any(ch['c'].strip() for ch in g) else g[0]['bbox'][0]
                    x1 = max(ch['bbox'][2] for ch in g)
                    y0, y1 = s['bbox'][1], s['bbox'][3]
                    out.append(dict(t=t, x0=x0, x1=x1, y0=y0, y1=y1, yc=(y0 + y1) / 2, color=s['color'], size=s['size']))
    return out


def rows_of(spans, tol=2.6):
    rows = []
    for s in sorted(spans, key=lambda s: s['yc']):
        if rows and abs(s['yc'] - rows[-1]['yc']) <= tol:
            rows[-1]['spans'].append(s)
            rows[-1]['yc'] = sum(x['yc'] for x in rows[-1]['spans']) / len(rows[-1]['spans'])
        else:
            rows.append(dict(yc=s['yc'], spans=[s]))
    for r in rows:
        r['spans'].sort(key=lambda s: s['x0'])
        r['y0'] = min(s['y0'] for s in r['spans'])
        r['y1'] = max(s['y1'] for s in r['spans'])
    return rows


def cluster(vals, tol):
    groups = []
    for v in sorted(vals):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [min(g) for g in groups]


def norm(t):
    t = t.replace('<=', '≤ ').replace('>=', '≥ ')
    t = re.sub(r'LUC\s*p\s*', 'LUC•', t)
    t = re.sub(r'(\d)\s*-\s*(\d)', r'\1-\2', t)
    t = re.sub(r'(^|\s)y\s*(?=\d)', r'\1≤ ', t)
    t = re.sub(r'(^|\s)u\s*(?=\d)', r'\1≥ ', t)
    return re.sub(r'\s+', ' ', t).strip()


def page_meta(page):
    txt = page.get_text()
    up = ' '.join(re.findall(r'^Upstream: (.*)$', txt, re.M)).strip()
    dn = ' '.join(re.findall(r'^Downstream: (.*)$', txt, re.M)).strip()
    m = re.search(r'Ue:\s*([^\n]*V(?:\s*AC)?)', txt)
    volt = m.group(1).strip() if m else ''
    if volt and 'AC' not in volt:
        volt += ' AC'
    refs = re.findall(r'\bA-\d+\b', txt)
    return dict(up=up, dn=dn, voltage=volt, ref=refs[-1] if refs else '')


def parse_table(rows, ui):
    """rows: all rows of the page; ui: index of the row holding the white 'Upstream' label."""
    # downstream header row + band text "Selectivity limit ..." gives the start of the value columns
    di = next(i for i in range(ui + 1, len(rows)) if any(s['t'].startswith('Downstream') for s in rows[i]['spans']))
    band = [s for r in rows[di:di + 3] for s in r['spans'] if re.match(r'Selectivity', s['t'])]
    if not band:
        return None
    X0 = band[0]['x0'] - 2
    left0 = next(s['x0'] for s in rows[ui]['spans'] if s['t'].startswith('Upstream'))

    # downstream label rows: from the Downstream row until the first row with a value cell
    bi = di
    while bi < len(rows) and not any(CELL_RE.match(s['t']) for s in rows[bi]['spans']):
        bi += 1
    labels = [s for r in rows[di:bi] for s in r['spans'] if s['x0'] < X0 and DN_LABELS.match(s['t'])]
    lcols = [dict(x=left0, name='family')]
    for x in cluster([s['x0'] for s in labels if s['x0'] > left0 + 15], 4):
        txt = ' '.join(s['t'] for s in labels if abs(s['x0'] - x) < 4)
        name = ('rating' if re.match(r'Rating|In\b', txt) else 'icu' if txt.startswith('Icu') else
                'icn' if txt.startswith('Icn') else 'trip' if re.match(r'Trip|Thermal', txt) else txt)
        lcols.append(dict(x=x, name=name))

    # body rows: consecutive rows (gap < 8 pt) after the labels
    body = []
    prev_y1 = rows[bi - 1]['y1']
    for r in rows[bi:]:
        if r['y0'] - prev_y1 > 8 or any(s['t'].startswith('Upstream') for s in r['spans']):
            break
        # legend box / notes below the table: no value cells and nothing in the rating column
        if body and not any(s['x0'] >= X0 - 1 for s in r['spans']) and (
                any(LEGEND_RE.match(s['t']) or len(s['t']) > 60 for s in r['spans'])
                or not any(re.match(r'^[≤y<]?\s*\d', s['t']) for s in r['spans'] if s['x0'] > left0 + 15)
                and any(re.match(r'^\d', s['t']) for s in r['spans'])):
            break
        body.append(r)
        prev_y1 = r['y1']

    # header rows: Upstream row .. row before Downstream
    head = rows[ui:di]
    leaf = head[-1]
    leaf_x = []
    for s in leaf['spans']:
        if s['x0'] >= X0 - 1 and not (leaf_x and leaf_x[-1][1] in ('y', 'u', '≤', '≥')):
            leaf_x.append((s['x0'], s['t']))
        elif leaf_x:
            leaf_x[-1] = (leaf_x[-1][0], s['t'])
    anchors = cluster([s['x0'] for r in body for s in r['spans'] if s['x0'] >= X0 - 1] + [x for x, _ in leaf_x], 6)
    n = len(anchors)

    def col_of(x, strict=True):
        best = min(range(n), key=lambda i: abs(anchors[i] - x))
        if abs(anchors[best] - x) <= 6:
            return best
        if strict:
            return None
        c = [i for i in range(n) if anchors[i] >= x - 6]
        return c[0] if c else None

    cols = [dict(product=[], icu='', trip='', rating='', setting='') for _ in range(n)]
    for r in head:
        lab = ' '.join(s['t'] for s in r['spans'] if s['x0'] < X0 - 1 and not s['t'].startswith('Upstream'))
        right = []
        for s in r['spans']:
            if s['x0'] < X0 - 1:
                continue
            if right and right[-1]['t'] in ('y', 'u', '≤', '≥', '<', '>'):   # "≤" glyph is a separate span
                right[-1] = dict(right[-1], t=right[-1]['t'] + ' ' + s['t'], x1=s['x1'])
            else:
                right.append(dict(s))
        starts = []
        for s in right:
            c = col_of(s['x0'], strict=False)
            if c is None:
                continue
            if starts and starts[-1][0] == c:
                starts[-1] = (c, starts[-1][1] + ' ' + s['t'])
            else:
                starts.append((c, s['t']))
        key = ('icu' if lab.startswith('Icu') else 'trip' if lab.startswith('Trip') else
               'setting' if lab.startswith('Setting') else 'rating' if lab.startswith('Rating') else 'product')
        for k, (c, t) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else n
            # leaf rows (rating / setting) never span: one value per column
            if key in ('rating', 'setting') and len(starts) == n:
                end = c + 1
            for i in range(c, end):
                if key == 'product':
                    cols[i]['product'].append(t)
                else:
                    cols[i][key] = norm(t)
    columns = [dict(c, product=norm(' '.join(c['product']))) for c in cols]

    out_rows, cells = [], []
    fam, icn = '', ''
    for r in body:
        lt = {}
        for s in r['spans']:
            if s['x0'] >= X0 - 1:
                continue
            name = ([lc['name'] for lc in lcols if lc['x'] - 3 <= s['x0']] or ['family'])[-1]
            lt[name] = (lt.get(name, '') + ' ' + s['t']).strip()
        vals = [None] * n
        for s in r['spans']:
            if s['x0'] >= X0 - 1:
                c = col_of(s['x0'])
                if c is not None:
                    vals[c] = ((vals[c] + ' ') if vals[c] else '') + s['t']
        f = lt.get('family', '')
        if f:
            if DEVICE_RE.match(f) or not fam:
                fam, icn = f, ''
                out_rows_start = len(out_rows)
            else:   # continuation line of the family name ("TM-D", "Limiter block", "VD")
                fam = fam + ' ' + f
                for o in out_rows[out_rows_start:]:
                    o['family'] = fam
        if 'icn' in lt:
            icn = lt['icn'] if re.match(r'^\d{3,}', lt['icn']) or not icn else icn + ' ' + lt['icn']
            for o in out_rows[out_rows_start:]:
                if o['icn'] and icn.startswith(o['icn']):
                    o['icn'] = icn
        if not any(vals) and not lt.get('rating') and not lt.get('icu'):
            continue
        out_rows.append(dict(family=fam, rating=norm(lt.get('rating', '')), icu=norm(lt.get('icu', '')),
                             trip=norm(lt.get('trip', '')), icn=icn))
        cells.append([norm(v).replace('—', '-').replace('–', '-').replace(' ', '') if v else None for v in vals])
    # catalogue misprint (A-234): rating values printed in the Icu column for some rows of a family
    fams = {}
    for o in out_rows:
        fams.setdefault(o['family'], []).append(o)
    for rs in fams.values():
        if len(rs) > 1 and any(o['rating'] for o in rs):
            for o in rs:
                if not o['rating'] and o['icu']:
                    o['rating'], o['icu'] = o['icu'], ''
    return dict(columns=columns, rows=out_rows, cells=cells)


def parse_page(doc, pno):
    page = doc[pno - 1]
    rows = rows_of(spans_of(page))
    meta = page_meta(page)
    tables = []
    ups = [i for i, r in enumerate(rows) if any(re.match(r'^Upstream( CB)?$', s['t']) and s['color'] == 0xffffff for s in r['spans'])]
    for ti, ui in enumerate(ups):
        t = parse_table(rows, ui)
        if t and t['rows']:
            t.update(page=pno, tableIndex=ti, **meta)
            tables.append(t)
    return tables


def main():
    doc = pymupdf.open(PDF)
    pages = []
    for part in PAGES.split(','):
        a, _, b = part.partition('-')
        pages += list(range(int(a), int(b or a) + 1))
    allt = []
    for p in pages:
        try:
            allt += parse_page(doc, p)
        except Exception as e:  # noqa: BLE001
            print('ERR page', p, repr(e))
    json.dump(allt, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('tables', len(allt), 'cells', sum(len(r) for t in allt for r in t['cells']))


main()
