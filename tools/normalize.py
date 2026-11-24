"""Normalise Schneider table labels into structured device descriptions.

A table header such as "MasterPacT MTZ1 06/08/10/12/16 H1/H2/H3 MicroLogic 5&6.0 A/E/X - 7.0X Inst : OFF"
becomes   series="MasterPacT MTZ1", perfs={"H1","H2","H3"}, trips={"MicroLogic 5.0/6.0/7.0 – Inst OFF"}.

The app then lets the user choose series -> udførelse (perf) -> udløser (trip) -> In -> Ir instead of
picking among hundreds of slightly different raw labels.
"""
import re

STD = [0.5, 1, 1.6, 2, 3, 4, 6, 8, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160,
       200, 250, 320, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6300]

NSX_SIZES = [100, 160, 250, 400, 630]


def _clean(s):
    s = (s or '').replace('�', '').replace(' ', ' ').replace('…', '...')
    s = re.sub(r'\[\s*\d+\s*\]|\(\d\)', ' ', s)            # footnote markers
    s = re.sub(r'Com[Pp]ac[Tt]\s*', '', s)                 # ComPacT / Compact prefix
    s = re.sub(r'Master[Pp]ac[Tt]\s*', '', s)
    s = re.sub(r'Fu[Pp]ac[Tt]\s*', '', s)
    s = re.sub(r'Acti\s?9\s*', '', s)
    s = re.sub(r'(?<![\w.])y\s*(?=\d)', '≤ ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _letters(seg, allowed):
    """Performance letters like 'N/H/L', 'B/F/N/H/S/L/R', 'H1/H2/H3' found in seg."""
    out = []
    seg = re.sub(r'H1/2(?![\dV])', 'H1/H2', seg)
    seg = re.sub(r'\b\d\s?P(\d\s?D)?\b|\(\d\s?P/\d\s?P\)|\d\s?P(?=[/ ,)])', ' ', seg)   # pole designations 1P, 2P2D ...
    for tok in re.findall(r'(?<![A-Za-z])[A-Z][A-Z0-9]{0,2}V?(?![a-z])', seg):
        if tok in allowed and tok not in out:
            out.append(tok)
    return out


PERF_MCB = {'N', 'H', 'L', 'P'}
PERF_NSX = {'B', 'F', 'N', 'H', 'S', 'L', 'R', 'HB1', 'HB2', 'E', 'M'}
PERF_NS = {'N', 'H', 'L', 'LB'}
PERF_MTZ = {'N1', 'H1', 'H2', 'H2V', 'H3', 'L1', 'HA', 'HF', 'HH', 'NA'}

# (regex, series name or callable, allowed perf letters)
_PATTERNS = [
    (r'MTZ\s?([123])', lambda m: 'MasterPacT MTZ' + m.group(1), PERF_MTZ),
    (r'NW\s?\d{0,2}\s?DC', lambda m: 'MasterPacT NW DC', {'N', 'H'}),
    (r'NS\s?1600\s?b|NS\s?1600\s?-\s?3200|NS\s?1600 2000|NS\s?(?:2000|2500|3200)\b', lambda m: 'ComPacT NS1600b–3200', PERF_NS),
    (r'NS\s?(?:630\s?b|800|1000|1250|1600)(?![0-9])|\bNS\b(?!X)', lambda m: 'ComPacT NS630b–1600', PERF_NS),
    (r'NSX\s?(100|160|250|400|630|1200)\s?DC', lambda m: 'ComPacT NSX%s DC' % m.group(1), {'F', 'N', 'M', 'S'}),
    (r'NSXm', lambda m: 'ComPacT NSXm', {'E', 'B', 'F', 'N', 'H'}),
    (r'NSX\s?(100|160|250|400|630)?', None, PERF_NSX),          # handled specially (ranges, lists)
    (r'iC60\s?L\s?MA', lambda m: 'iC60L MA', set()),
    (r'NG125\s?L\s?MA', lambda m: 'NG125L MA', set()),
    (r'i\s?C60(?=[^,;]*RCBO)|i\s?C60\s?RCBO', lambda m: 'iC60 RCBO', PERF_MCB),
    (r'C60H-DC', lambda m: 'C60H-DC', set()),
    (r'iC60', lambda m: 'iC60', PERF_MCB),
    (r'i?C120', lambda m: 'C120', PERF_MCB),
    (r'NG125', lambda m: 'NG125', PERF_MCB),
    (r'iCVm40', lambda m: 'iCVm40', PERF_MCB),
    (r'[iI]CV40', lambda m: 'iCV40', PERF_MCB),
    (r'[iI]C40', lambda m: 'iC40', PERF_MCB),
    (r'iDPN', lambda m: 'iDPN', PERF_MCB),
    (r'NH\s?000', lambda m: 'NH-sikring (NH000–NH1)', set()),
    (r'\bg[Gg]\b|\bGG\b', lambda m: 'gG-sikring', set()),
    (r'\ba[Mm]\b|\bAM\b', lambda m: 'aM-sikring', set()),
    (r'GV\s?([2-6])', lambda m: 'TeSys GV%s' % m.group(1), {'ME', 'P', 'L', 'LE', 'PE', 'PEM'}),
    (r'LUB\s?(12|32|38)', lambda m: 'TeSys U LUB%s' % m.group(1), set()),
    (r'Integral\s?63', lambda m: 'Integral 63', set()),
]


def _nsx_sizes(text, m):
    """NSX100 160 250 / NSX100-250 / NSX100 to 630 / NSX100/160/250 -> list of sizes."""
    tail = text[m.start():m.start() + 40]
    rng = re.match(r'NSX\s?(\d{3})\s*(?:-|to)\s*(?:NSX\s?)?(\d{3,4})', tail)
    if rng:
        a, b = int(rng.group(1)), int(rng.group(2))
        return [n for n in NSX_SIZES if a <= n <= b]
    lst = re.match(r'NSX\s?(\d{3})((?:\s*[/ ,]\s*(?:NSX\s?)?(?:100|160|250|400|630)\b)*)', tail)
    if lst:
        return [int(lst.group(1))] + [int(x) for x in re.findall(r'(100|160|250|400|630)', lst.group(2))]
    return []


def series(text):
    """Return list of (series, [perf letters]) found in a label."""
    t = _clean(text)
    hits = []   # (start, end, name or list, allowed)
    taken = []
    for rx, fn, allowed in _PATTERNS:
        for m in re.finditer(rx, t):
            if any(a <= m.start() < b for a, b in taken):
                continue
            if fn is None:     # NSX
                sizes = _nsx_sizes(t, m)
                names = ['ComPacT NSX%d' % n for n in sizes] or ['ComPacT NSX']
            else:
                names = [fn(m)]
            taken.append((m.start(), m.end()))
            hits.append((m.start(), m.end(), names, allowed))
    hits.sort()
    out = []
    for i, (a, b, names, allowed) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(t)
        perfs = _letters(t[b:nxt], allowed) if allowed else []
        # letters glued to the series name: iC60N/H/L, NSX100B/F/N, MTZ2 08-20N1/H1
        for name in names:
            if not any(o[0] == name for o in out):
                out.append((name, perfs))
            else:
                for o in out:
                    if o[0] == name:
                        o[1].extend(p for p in perfs if p not in o[1])
    if not out:
        out = [(t, [])]
    return out


def trips(text):
    """Return list of trip-unit / curve labels in a label ('' = unspecified)."""
    t = _clean(text)
    res = []
    # curves
    m = re.search(r'[Cc]urves?\s*:?\s*([BCDKZ](?:\s*(?:,|-|/|and|&)\s*[BCDKZ])*)\b', t) \
        or re.search(r'\b([BCDKZ](?:\s*[-,/]\s*[BCDKZ])+)\s*[Cc]urves?', t) \
        or re.search(r'–\s*curve\s+([BCDKZ])\b', t) \
        or re.search(r'\b([BCDKZ])\s+[Cc]urves?\b', t)
    if m and not re.search(r'All curves', t):
        for c in re.findall(r'[BCDKZ]', m.group(1)):
            lab = 'Kurve ' + c
            if lab not in res:
                res.append(lab)
    # MicroLogic
    ml = re.search(r'Micro[Ll]ogic\s*(.*)', t)
    if ml:
        rest = ml.group(1)
        if re.match(r'\s*4\.1', rest):
            res.append('MicroLogic 4.1')
        elif re.match(r'\s*1\.0\s*DC', rest):
            res.append('MicroLogic 1.0 DC')
        elif re.match(r'\s*2\.0', rest) and not re.match(r'\s*2\.0\s*-\s*5', rest):
            res.append('MicroLogic 2.0 (Isd = 10 Ir)')
        elif re.match(r'\s*(5|2\.0\s*-\s*5)', rest):
            if re.search(r'Inst[^A-Za-z]*(position\s*)?OFF', rest):
                res.append('MicroLogic 5/6/7 – Inst OFF')
            elif re.search(r'Inst[^A-Za-z]*15', rest):
                res.append('MicroLogic 5/6/7 – Inst 15 In')
            else:
                res.append('MicroLogic 5/6/7')
        else:
            res.append('MicroLogic')
    # thermal-magnetic
    for rx, lab in ((r'TM-?DC\s*(min|max|Mini|Maxi)', None), (r'TM-?DC', 'TM-DC'), (r'TM-?D\b', 'TM-D'), (r'TM-?G', 'TM-G')):
        for mm in re.finditer(rx, t):
            l = lab or 'TM-DC ' + mm.group(1).lower().replace('mini', 'min').replace('maxi', 'max')
            if l not in res and not (l == 'TM-DC' and any(r.startswith('TM-DC ') for r in res)):
                res.append(l)
    if re.search(r'(?<![A-Za-z])MA(?![A-Za-z])', t) and 'MA' not in res and not any('MA' in r for r in res):
        res.append('MA')
    return res or ['']


def _num(s):
    return float(s.replace(',', '.'))


def fmt(n):
    return ('%g' % n).replace('.', ',') if isinstance(n, float) else str(n)


def up_rating(s):
    """'In 630 / Setting Ir 250' -> (In or None, setting label)."""
    s = _clean(s)
    s = re.sub(r'^[A-Z]\s+(?=Trip)', '', s)
    parts = [p.strip() for p in s.split('/') if p.strip()]
    In, rest = None, []
    i = 0
    while i < len(parts):
        p = parts[i]
        m = re.search(r'(\d+(?:[.,]\d+)?)', p)
        if In is None and m and re.match(r'^(In|Rating|Trip unit rating|CB Rating|\d)', p) and not re.search(r'\bIr\b|\bIm\b|kA', p):
            In = fmt(_num(m.group(1)))
        elif re.search(r'\bIr\b', p) and m:
            rest.append('Ir ' + m.group(1))
        elif not re.search(r'\d', p) and i + 1 < len(parts):      # "Im fixed" / "1400"
            rest.append(re.sub(r'\s+', ' ', p + ' ' + parts[i + 1]))
            i += 1
        elif re.match(r'^\d', p):
            rest.append('Ieq ' + p if In and not rest else p)
        else:
            rest.append(re.sub(r'Equivalent rated current', 'Ieq', p))
        i += 1
    return In, ' / '.join(rest)


def dn_rating(s, extra_std=()):
    """Downstream rating -> (list of In values as strings, Ir label, display label)."""
    raw = _clean(s)
    if not raw:
        return None, '', ''
    ir = ''
    m = re.search(r'Ir\s*(≤?\s*\d+(?:[.,]\d+)?(?:\s*-\s*\d+)?)', raw)
    if m:
        ir = 'Ir ' + m.group(1).replace(' ', '')
        raw_in = raw[:m.start()].strip(' /')
    else:
        raw_in = raw
    t = raw_in.strip()
    vals = None
    if re.fullmatch(r'\d+(?:[.,]\d+)?(?:\s*\(\w+\))?', t):
        vals = [fmt(_num(re.match(r'[\d.,]+', t).group(0)))]
    elif re.fullmatch(r'(≤|<|≥|>|u)\s*\d+(?:[.,]\d+)?', t):
        op = t[0]
        n = _num(re.search(r'[\d.,]+', t).group(0))
        if op in '≤<':
            vals = [fmt(x) for x in STD if x <= n and x >= 1] + ([] if n in STD else [fmt(n)])
        else:
            vals = [fmt(x) for x in STD if n <= x <= max(n * 4, 125)]
    elif re.fullmatch(r'\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?', t):
        a, b = [_num(x) for x in re.findall(r'[\d.,]+', t)]
        vals = [fmt(x) for x in STD if a <= x <= b]
        for e in (a, b):
            if fmt(e) not in vals:
                vals.append(fmt(e))
    elif re.fullmatch(r'\d+(?:[.,]\d+)?\s+\d+', t):          # DC: In + Im
        a = re.findall(r'[\d.,]+', t)
        vals = [fmt(_num(a[0]))]
        ir = (ir + ' / ' if ir else '') + 'Im ' + a[1]
    elif not t and ir:
        vals = None
    return vals, ir, raw
