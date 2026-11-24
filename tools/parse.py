import pymupdf, sys, re, json

PDF = sys.argv[1]
OUT = sys.argv[2]
PAGES = sys.argv[3] if len(sys.argv) > 3 else None

GREEN_FILL = (0.28, 0.68, 0.25)
BAND_FILL = (0.92, 0.95, 0.9)
RATING_KW = re.compile(r'^(Rating|In \(A\)|In\b|Ir\b|Ir \(A\)|Setting|Ir setting|Setting Ir|Irth|Ir th|Im$|Trip unit rating)', re.I)
HEADER_KW = re.compile(r'^(Upstream|Downstream|Trip unit|Rating|In \(A\)|Ir|Setting|Selectivity limit|Curve)', re.I)
HDR_LEFT_KW = re.compile(r'^(Upstream|Downstream|Down-|Trip unit|Rating|In \(A\)|In$|Ir\b|Ir \(A\)|Setting|Ir setting|Im$|Circuit|CB type|CB rating|or Trip|unit rating|rating \(A\)|\(A\)$|setting Ir)', re.I)
FOOT_RE = re.compile(r'^(\[\s*\d+\s*\]?|\]|\(\d+\))$')
LEGEND_RE = re.compile(r'^(Selectivity limit in kA|Selectivity limit =|Total selectivity|No selectivity|Note:|se\.com$|Selectivity, Cascading and Coordination Guide|\[\d+\]\s+\S)')
VALUE_RE = re.compile(r'^(T|\d+(?:[.,]\d+)?)$')
RATING_RE = re.compile(r'^(?:[≤<>⩽≥yu]\s*)?\d+(?:[.,]\d+)?(?:\s*-\s*\d+)?(?:\s*\(\w+\))?$')


def close(c, ref, tol=0.012):
    return c is not None and len(c) == 3 and all(abs(a - b) < tol for a, b in zip(c, ref))


def spans_of(page):
    out = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                t = s['text'].replace('\xa0', ' ').replace('�', '').strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s['bbox']
                out.append(dict(t=t, x0=x0, x1=x1, y0=y0, y1=y1, yc=(y0 + y1) / 2,
                                color=s['color'], bold='Bold' in s['font'], size=s['size']))
    return out


def cluster(vals, tol):
    vals = sorted(vals)
    groups = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [min(g) for g in groups]


def rows_of(spans, tol=2.6):
    spans = sorted(spans, key=lambda s: s['yc'])
    rows = []
    for s in spans:
        if rows and abs(s['yc'] - rows[-1]['yc']) <= tol:
            rows[-1]['spans'].append(s)
            rows[-1]['yc'] = sum(x['yc'] for x in rows[-1]['spans']) / len(rows[-1]['spans'])
        else:
            rows.append(dict(yc=s['yc'], spans=[s]))
    for r in rows:
        r['spans'].sort(key=lambda s: s['x0'])
    return rows


def page_meta(spans, page):
    txt = page.get_text()
    up = re.findall(r'^Upstream: (.*)$', txt, re.M)
    dn = re.findall(r'^Downstream: (.*)$', txt, re.M)
    volt = ''
    for s in spans:
        if s['size'] > 11 and re.search(r'V\s*(AC|DC)|V Ph', s['t']):
            volt = s['t']
            break
    # unit
    unit = 'kA'
    if re.search(r'Selectivity\s*limit\s*\(A\)', txt):
        unit = 'A'
    elif re.search(r'Selectivity\s*limit\s*\(kA\)', txt) or re.search(r'in kA', txt):
        unit = 'kA'
    else:
        leg = [s for s in spans if 'Selectivity limit =' in s['t']]
        if leg:
            l = leg[0]
            box = [s for s in spans if abs(s['yc'] - l['yc']) < 3 and s['x1'] < l['x0'] and VALUE_RE.match(s['t'])]
            if box and float(box[0]['t'].replace(',', '.')) >= 100:
                unit = 'A'
    return dict(up=' '.join(up).strip(), dn=' '.join(dn).strip(), voltage=volt.replace('y', '≤').strip(), unit=unit)


def parse_page(doc, pno):
    page = doc[pno - 1]
    spans = spans_of(page)
    meta = page_meta(spans, page)
    drawings = page.get_drawings()
    rects = []  # (rect, fill)
    hlines = []
    for g in drawings:
        for it in g['items']:
            if it[0] == 're':
                fill = g.get('fill')
                rects.append((it[1], tuple(fill) if fill else None))
                if g.get('color') is not None and g['type'] in ('s', 'fs') and max(g['color']) < 0.5:
                    r = it[1]
                    hlines.append((r.y0, r.x0, r.x1)); hlines.append((r.y1, r.x0, r.x1))
            elif it[0] == 'l':
                a, b = it[1], it[2]
                col = g.get('color')
                if abs(a.y - b.y) < 0.6 and col is not None and max(col) < 0.5:
                    hlines.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
    bands = [r for r, f in rects if close(f, BAND_FILL)]
    greens = [r for r, f in rects if close(f, GREEN_FILL)]

    ups = sorted([s for s in spans if re.match(r'^Upstream( CB)?$', s['t']) and s['color'] == 0xffffff], key=lambda s: s['y0'])
    legend_y = page.rect.y1
    tables = []
    for ti, u in enumerate(ups):
        top = u['y0'] - 1
        bottom = ups[ti + 1]['y0'] - 1 if ti + 1 < len(ups) else legend_y
        # legend could be between tables
        legs = [s['y0'] for s in spans if s['y0'] > top and s['y0'] < bottom and (LEGEND_RE.match(s['t']) or len(s['t']) > 70)]
        if legs:
            bottom = min(legs)
        tsp = [s for s in spans if top <= s['yc'] < bottom and not re.match(r'^A-\d+$', s['t'])]
        # footnote markers: attach '*' to preceding value, then drop
        tsp = [dict(s) for s in tsp]
        for f in [s for s in tsp if FOOT_RE.match(s['t'])]:
            prev = [s for s in tsp if s is not f and not FOOT_RE.match(s['t']) and abs(s['yc'] - f['yc']) < 4
                    and -1 <= f['x0'] - s['x1'] <= 4]
            if prev and VALUE_RE.match(prev[0]['t'].rstrip('*')):
                prev[0]['t'] = prev[0]['t'].rstrip('*') + '*'
        tsp = [s for s in tsp if not FOOT_RE.match(s['t'])]
        t = parse_table(tsp, u, rects, greens, bands, hlines)
        if t:
            refs = [s['t'] for s in spans if re.match(r'^[A-E]-\d+$', s['t'])]
            t.update(page=pno, ref=refs[0] if refs else 'A-%d' % (pno - 4), **meta)
            nums = [float(v.rstrip('*').replace(',', '.')) for row in t['cells'] for v in row
                    if v and re.match(r'^\d+(?:[.,]\d+)?\*?$', v)]
            if t['unit'] == 'A' and nums and max(nums) < 100 and any(n != int(n) for n in nums):
                t['unit'] = 'kA'
            for r in t['rows']:
                if not r['family'] or re.match(r'^(Curve|–)', r['family']):
                    r['family'] = (t['dn'] + ' – ' + r['family']).strip(' –')
            t['tableIndex'] = ti
            tables.append(t)
    return tables


def parse_table(tsp, u, rects, greens, bands, hlines):
    # X0: start of data columns = x0 of upstream product name in the Upstream row
    row0 = [s for s in tsp if s['y0'] < u['y1'] - 1 and s['y1'] > u['y0'] + 1 and s['x0'] > u['x1'] + 2]
    if not row0:
        return None
    X0 = min(s['x0'] for s in row0) - 3
    rows = rows_of(tsp)
    for r in rows:
        d = [s for s in r['spans'] if s['t'] in ('Downstream', 'Down-', 'Downstream CB')]
        if d:
            nxt = [s for s in r['spans'] if s['x0'] > d[0]['x1'] + 2]
            if len(nxt) >= 2 and nxt[0]['x0'] >= X0 - 1 and RATING_KW.match(nxt[0]['t']):
                X0 = nxt[1]['x0'] - 3
            break
    # classify rows: header = up to last keyword/white row (stop at first band or data row)
    for r in rows:
        r['band'] = any(re.match(r'Selectivity\s*limit', s['t']) for s in r['spans'] if s['x0'] < X0 - 1)
    last_hdr = -1
    for i, r in enumerate(rows):
        left = [s for s in r['spans'] if s['x0'] < X0]
        if r['band']:
            break
        is_kw = any(HDR_LEFT_KW.match(s['t']) for s in left)
        white = any(s['color'] == 0xffffff for s in r['spans'])
        if is_kw or white:
            last_hdr = i
    header_rows = rows[:last_hdr + 1]
    body_rows = [r for r in rows[last_hdr + 1:]]
    # leading rows before first band that only carry downstream context (e.g. "3P, 3P+N")
    while body_rows and not body_rows[0]['band'] and not any(s['x0'] >= X0 - 1 for s in body_rows[0]['spans']) \
            and not any(RATING_RE.match(s['t']) for s in body_rows[0]['spans']):
        header_rows.append(body_rows.pop(0))
    if not body_rows:
        return None
    body_top = min(s['y0'] for r in body_rows for s in r['spans'])
    body_bottom = max(s['y1'] for r in body_rows for s in r['spans'])
    tableLeft = u['x0']

    # downstream rating column x
    ratingX = None
    dhdr = None
    for r in header_rows:
        sp = r['spans']
        d = [s for s in sp if s['t'] in ('Downstream', 'Down-', 'Downstream CB')]
        if d:
            nxt = [s for s in sp if s['x0'] > d[0]['x1'] + 2 and s['x0'] < X0]
            if nxt:
                ratingX = min(s['x0'] for s in nxt)
                dhdr = r
    # 2026 layout: separate "CB rating" and "Trip unit setting Ir" columns
    cbX = irX = None
    for r in header_rows:
        for s in r['spans']:
            if s['x0'] < X0 and s['x0'] > tableLeft + 20:
                if re.match(r'^CB rating', s['t']) and cbX is None:
                    cbX = s['x0']
                if re.match(r'^Trip unit$|^Trip unit setting|^setting Ir', s['t']) and irX is None and cbX is not None and s['x0'] > cbX + 5:
                    irX = s['x0']
    if cbX is not None:
        ratingX = cbX
    if ratingX is None:
        c = [s['x0'] for r in header_rows for s in r['spans'] if s['x0'] < X0 and s['x0'] > tableLeft + 20 and re.match(r'^(Rating|CB rating)', s['t'])]
        if c:
            ratingX = min(c)
    if ratingX is None:
        cand = [s['x0'] for r in body_rows for s in r['spans'] if s['x0'] < X0 and RATING_RE.match(s['t'])]
        ratingX = max(cluster(cand, 4)) if cand else X0
    # downstream context text (e.g. 1P+N / 3P, 3P+N, 2P single-phase)
    ctx = []
    if dhdr is not None:
        i = header_rows.index(dhdr)
        for r in header_rows[i:]:
            for s in r['spans']:
                if ratingX - 3 <= s['x0'] < X0 and not RATING_KW.match(s['t']):
                    ctx.append(s['t'])
    familyX = min([s['x0'] for r in body_rows for s in r['spans'] if s['x0'] < ratingX - 3] or [ratingX - 50])

    # columns
    xs = [s['x0'] for r in body_rows for s in r['spans'] if s['x0'] >= X0 - 1]
    rating_hdr_rows = [r for r in header_rows if any(RATING_KW.match(s['t']) for s in r['spans'] if s['x0'] < X0)]
    xs += [s['x0'] for r in rating_hdr_rows for s in r['spans'] if s['x0'] >= X0 - 1]
    anchors = cluster(xs, 5)
    if not anchors:
        return None

    def col_of(x):
        best = min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))
        return best if abs(anchors[best] - x) <= 6 else None

    def containing_rect(s):
        cx, cy = (s['x0'] + s['x1']) / 2, s['yc']
        c = [r for r, f in rects if f is not None and r.x0 - 0.5 <= s['x0'] and r.x1 + 0.5 >= cx and r.y0 - 0.5 <= cy <= r.y1 + 0.5 and r.width > 5]
        return min(c, key=lambda r: r.width) if c else None

    ncol = len(anchors)
    prod = [[] for _ in range(ncol)]
    rat = [[] for _ in range(ncol)]
    for r in header_rows:
        right = [s for s in r['spans'] if s['x0'] >= X0 - 1 and not re.match(r'Selectivity\s*limit', s['t'])]
        left = [s for s in r['spans'] if s['x0'] < X0]
        is_rating = any(RATING_KW.match(s['t']) for s in left) or bool(right and all(VALUE_RE.match(s['t']) and s['t'] != 'T' and not s['t'].startswith('0') for s in right))
        lab = ' '.join(s['t'] for s in left if s['t'] not in ('Downstream', 'Upstream', 'Trip unit', 'Down-', 'stream') and s['x0'] < ratingX - 3 or RATING_KW.match(s['t']))
        # merge spans that are visually one cell text (gap small)
        merged = []
        for s in right:
            if merged and s['x0'] - merged[-1]['x1'] < 2.5 and col_of(s['x0']) is None:
                merged[-1] = dict(merged[-1], t=merged[-1]['t'] + ' ' + s['t'], x1=s['x1'])
            elif merged and s['x0'] - merged[-1]['x1'] < 2.5 and col_of(s['x0']) == col_of(merged[-1]['x0']):
                merged[-1] = dict(merged[-1], t=merged[-1]['t'] + ' ' + s['t'], x1=s['x1'])
            else:
                merged.append(dict(s))
        starts = []
        for s in merged:
            c = col_of(s['x0'])
            if c is None:
                # find first anchor >= x0-6
                cands = [i for i in range(ncol) if anchors[i] >= s['x0'] - 6]
                c = cands[0] if cands else None
            if c is None:
                continue
            starts.append((c, s))
        cover = []
        for k, (c, s) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else ncol
            rc = containing_rect(s)
            if rc is not None:
                e2 = len([a for a in anchors if a < rc.x1 - 1])
                if e2 > c:
                    end = min(end, e2)
            cover.append([c, end, s['t']])
        # consecutive single-column rule
        if len(cover) >= 3 and all(cv[1] - cv[0] == 1 for cv in cover[:-1]) and all(cover[k + 1][0] == cover[k][0] + 1 for k in range(len(cover) - 1)):
            cover[-1][1] = cover[-1][0] + 1
        for c, e, txt in cover:
            for i in range(c, e):
                if is_rating:
                    rat[i].append((lab, txt))
                else:
                    prod[i].append(txt)
    upName = ' '.join(s['t'] for s in sorted(row0, key=lambda s: s['x0']))
    columns = []
    for i in range(ncol):
        rp = []
        for lab, txt in rat[i]:
            lab2 = re.sub(r'\s*\(A\)', '', lab)
            lab2 = re.sub(r'\b(Downstream|Upstream|Down-|stream)\b', '', lab2).strip()
            rp.append((lab2 + ' ' if lab2 else '') + txt)
        pr = re.sub(r'\s+', ' ', ' '.join(dict.fromkeys(prod[i]))).strip()
        if not pr:
            pr = upName
        columns.append(dict(product=pr, rating=' / '.join(rp)))

    # family boundaries
    fx = familyX + 4
    bnd = sorted(set(round(y, 1) for (y, x0, x1) in hlines if x0 - 0.5 <= fx <= x1 + 0.5 and body_top - 3 <= y <= body_bottom + 3))
    for b in bands:
        if b.y0 >= body_top - 3 and b.x0 - 0.5 <= fx <= b.x1 + 0.5 and b.width > 100:
            bnd += [b.y0, b.y1]
    bnd = sorted(bnd)

    def seg_of(y):
        k = 0
        for b in bnd:
            if y > b:
                k += 1
        return k

    # middle label column (e.g. "Curve" B/C/D in DC tables): short texts in a column between family and rating
    midX = None
    mids = [s['x0'] for r in body_rows if not r['band'] for s in r['spans']
            if familyX + 25 < s['x0'] < ratingX - 3 and len(s['t']) <= 3]
    if len(mids) >= 2:
        midX = cluster(mids, 4)[0]

    def is_mid(s):
        return midX is not None and abs(s['x0'] - midX) < 5 and len(s['t']) <= 3

    fam_text = {}
    for r in body_rows:
        if r['band']:
            continue
        for s in r['spans']:
            if s['x0'] < ratingX - 3 and not is_mid(s):
                fam_text.setdefault(seg_of(s['yc']), []).append(s['t'])
    out_rows, cells = [], []
    cur_mid, cur_seg = '', None
    cur_cb, cur_cb_seg = '', None
    for r in body_rows:
        if r['band']:
            continue
        sg = seg_of(r['yc'])
        if sg != cur_seg:
            cur_mid, cur_seg = '', sg
        for s in r['spans']:
            if is_mid(s):
                cur_mid = s['t']
        right = [s for s in r['spans'] if s['x0'] >= X0 - 1 and not re.match(r'Selectivity\s*limit', s['t'])]
        if irX is not None:
            cb = ' '.join(s['t'] for s in r['spans'] if ratingX - 3 <= s['x0'] < irX - 3)
            ir = ' '.join(s['t'] for s in r['spans'] if irX - 3 <= s['x0'] < X0)
            if sg != cur_cb_seg:
                cur_cb, cur_cb_seg = '', sg
            if cb:
                cur_cb = cb
            rt = (f"{cur_cb} / Ir {ir}" if cur_cb else f"Ir {ir}") if ir else cb
        else:
            rt = ' '.join(s['t'] for s in r['spans'] if ratingX - 3 <= s['x0'] < X0)
        rt = re.sub(r'^y\s*', '≤ ', rt)
        rt = re.sub(r'^u\s*', '≥ ', rt)
        if not right and not rt:
            continue  # pure family continuation line
        vals = [None] * ncol
        for s in right:
            c = col_of(s['x0'])
            if c is None:
                continue
            v = s['t']
            vals[c] = (vals[c] + ' ' + v) if vals[c] else v
        fam = ' '.join(fam_text.get(sg, []))
        if cur_mid:
            fam = fam + ' – curve ' + cur_mid
        out_rows.append(dict(family=fam, rating=rt))
        cells.append(vals)
    return dict(X0=round(X0, 1), ratingX=round(ratingX, 1), dnContext=' '.join(ctx), columns=columns, rows=out_rows, cells=cells)


def main():
    doc = pymupdf.open(PDF)
    if PAGES:
        pages = []
        for part in PAGES.split(','):
            if '-' in part:
                a, b = part.split('-')
                pages += list(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))
    else:
        pages = list(range(19, 143)) + list(range(147, 157))
    allt = []
    for p in pages:
        try:
            allt += parse_page(doc, p)
        except Exception as e:
            print('ERR page', p, e)
    json.dump(allt, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('tables', len(allt))


main()



