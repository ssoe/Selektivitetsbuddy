// Selektivitetsbuddy – app-logik. build.py indsætter DATA og denne fil direkte i index.html.
// Hver tabel: cols = upstream-komponenter, rows = downstream-komponenter, cells[row][col] = værdi.
// Kolonner og rækker er normaliseret til k = [[serie, [udførelser], [udløsere]], ...], In / v (mærkestrøm) og
// st / ir (indstilling), så brugeren vælger trinvist i stedet for blandt hundredvis af rå tabelnavne.

// PDF'erne lægges valgfrit ved siden af index.html (de er ikke med i git-repo'et).
const PDFS = {
  "2026": { file: "Selektivitetstabeller 2026.pdf", name: "Selectivity, Cascading and Coordination Guide (2026)" },
  "2019": { file: "Schneider - Selektivitetstabeller.pdf", name: "Complementary technical information (2019)" },
};
const pdfAvailable = {};
for (const [k, p] of Object.entries(PDFS)) {
  pdfAvailable[k] = location.protocol === "file:"; // fetch virker ikke på file://
  fetch(encodeURI(p.file), { method: "HEAD" }).then(r => { pdfAvailable[k] = r.ok; render(); }).catch(() => {});
}

const $ = id => document.getElementById(id);
const uniq = a => [...new Set(a)];
const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const fmt = n => n.toLocaleString("da-DK", { maximumFractionDigits: 3 });
const nums = s => (String(s).match(/\d+(?:[.,]\d+)?/g) || []).map(x => parseFloat(x.replace(",", ".")));
function cmpNum(a, b) {
  const x = nums(a), y = nums(b);
  if (!x.length && y.length) return 1;
  if (x.length && !y.length) return -1;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] ?? -1) - (y[i] ?? -1);
    if (d) return d;
  }
  return String(a).localeCompare(String(b), "da");
}

// ---------- kategorier til serie-listen ----------
function category(s) {
  if (/sikring/.test(s)) return "Sikringer";
  if (/DC$/.test(s) || s === "C60H-DC") return "DC-afbrydere";
  if (/^(iC|iD|C120|NG125|iCV)/.test(s) && !/MA$/.test(s)) return "Acti9 / modulære (MCB)";
  if (/NSX/.test(s)) return "ComPacT NSX / NSXm (MCCB)";
  if (/ComPacT NS/.test(s)) return "ComPacT NS";
  if (/MasterPacT/.test(s)) return "MasterPacT (ACB)";
  return "Motorbeskyttelse";
}
const CAT_ORDER = ["Sikringer", "Acti9 / modulære (MCB)", "ComPacT NSX / NSXm (MCCB)", "ComPacT NS", "MasterPacT (ACB)", "DC-afbrydere", "Motorbeskyttelse"];

// ---------- tilstand ----------
const blank = () => ({ s: null, p: null, t: null, i: null, x: null });
const S = { volt: "", up: blank(), dn: blank() };

const tablesV = () => DATA.filter(t => !S.volt || t.volt === S.volt);

// matcher én k-nøgle mod et (delvist) valg. Tom udførelses-/udløserliste i tabellen = gælder alle.
const keyOk = (k, sel) => k[0] === sel.s
  && (sel.p == null || !k[1].length || k[1].includes(sel.p))
  && (sel.t == null || k[2].includes("") || k[2].includes(sel.t));

function colOk(c, sel, upTo) {
  if (!c.k.some(k => keyOk(k, { s: sel.s, p: upTo > 1 ? sel.p : null, t: upTo > 2 ? sel.t : null }))) return false;
  if (upTo > 3 && sel.i != null && c.In !== sel.i) return false;
  if (upTo > 4 && sel.x != null && c.st !== sel.x) return false;
  return true;
}
function rowOk(r, sel, upTo) {
  if (!r.k.some(k => keyOk(k, { s: sel.s, p: upTo > 1 ? sel.p : null, t: upTo > 2 ? sel.t : null }))) return false;
  if (upTo > 3 && sel.i != null) {
    const all = !r.v && !r.lab;
    if (!all && !(r.v && r.v.includes(sel.i)) && !(!r.v && r.lab === sel.i)) return false;
  }
  if (upTo > 4 && sel.x != null && r.ir && r.ir !== sel.x) return false;
  return true;
}

// ---------- formular ----------
const STEPS = [
  { key: "s", label: "Serie" },
  { key: "p", label: "Udførelse" },
  { key: "t", label: "Udløser / kurve" },
  { key: "i", label: "Mærkestrøm In (A)" },
  { key: "x", label: "Indstilling" },
];

function buildForm(side) {
  const box = $(side + "Form");
  box.innerHTML = STEPS.map((st, n) =>
    `<div class="step" id="${side}_row_${st.key}"><label for="${side}_${st.key}">${st.label}</label><select id="${side}_${st.key}"></select></div>`
  ).join("") + `<div class="note" id="${side}_note"></div>`;
  STEPS.forEach((st, n) => {
    $(`${side}_${st.key}`).addEventListener("change", e => {
      const sel = S[side];
      sel[st.key] = e.target.value === "\u0000" ? null : e.target.value;
      for (const later of STEPS.slice(n + 1)) sel[later.key] = null;   // nulstil efterfølgende trin
      if (side === "up") S.dn = keepDn();
      render();
    });
  });
}
function keepDn() { return S.dn; }   // ugyldige valg ryddes automatisk i renderSide

function fillSelect(id, options, value, labelFn, placeholder) {
  const el = $(id);
  el.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = "\u0000"; ph.textContent = placeholder;
  el.appendChild(ph);
  let groups = null;
  if (options.length && typeof options[0] === "object") groups = options;
  if (groups) {
    for (const g of groups) {
      const og = document.createElement("optgroup"); og.label = g.label;
      for (const v of g.items) { const o = document.createElement("option"); o.value = v; o.textContent = labelFn(v); og.appendChild(o); }
      el.appendChild(og);
    }
  } else {
    for (const v of options) { const o = document.createElement("option"); o.value = v; o.textContent = labelFn(v); el.appendChild(o); }
  }
  el.value = value == null ? "\u0000" : value;
}

// Udfyld ét sides trin. items: liste af {obj, ok(sel, upTo)} hvor obj er kolonne eller række.
function renderSide(side, items, kind) {
  const sel = S[side];
  const show = (key, on) => $(`${side}_row_${key}`).classList.toggle("off", !on);

  // 1. serie
  const series = uniq(items.flatMap(it => it.k.map(k => k[0])));
  if (sel.s && !series.includes(sel.s)) Object.assign(sel, blank());
  const groups = CAT_ORDER.map(c => ({ label: c, items: series.filter(s => category(s) === c).sort((a, b) => a.localeCompare(b, "da", { numeric: true })) }))
    .filter(g => g.items.length);
  fillSelect(`${side}_s`, groups, sel.s, v => v, series.length ? "— vælg serie —" : "Vælg først upstream");
  $(`${side}_s`).disabled = !series.length;
  if (!sel.s) { ["p", "t", "i", "x"].forEach(k => show(k, false)); $(`${side}_note`).textContent = ""; return []; }

  const ok = (it, upTo) => kind === "col" ? colOk(it, sel, upTo) : rowOk(it, sel, upTo);

  // 2. udførelse
  let m = items.filter(it => ok(it, 1));
  const perfs = uniq(m.flatMap(it => it.k.filter(k => k[0] === sel.s).flatMap(k => k[1])));
  // motorværn: "udførelsen" er typen (GV2ME, GV2P, GV2L …), vist med fuld typebetegnelse
  const gv = /^TeSys (GV\d)$/.exec(sel.s);
  const PERF_ORDER = gv ? ["ME", "P", "PE", "PEM", "L", "LE"]
    : ["E", "B", "F", "N", "H", "S", "L", "LB", "R", "P", "M", "HB1", "HB2", "N1", "H1", "H2", "H2V", "H3", "L1", "HA", "HF", "HH", "NA"];
  perfs.sort((a, b) => PERF_ORDER.indexOf(a) - PERF_ORDER.indexOf(b));
  if (sel.p && !perfs.includes(sel.p)) sel.p = null;
  if (perfs.length === 1) sel.p = perfs[0];
  show("p", perfs.length > 1);
  $(`${side}_row_p`).querySelector("label").textContent = gv ? "Type" : STEPS[1].label;
  // downstream: udførelse er valgfri (påvirker sjældent tabellerne); upstream skal vælges
  fillSelect(`${side}_p`, perfs, sel.p, v => gv ? gv[1] + v : v,
    side === "dn" ? (gv ? "Alle typer" : "Alle udførelser") : "— vælg —");

  // 3. udløser / kurve
  m = items.filter(it => ok(it, 2));
  const trips = uniq(m.flatMap(it => it.k.filter(k => k[0] === sel.s).flatMap(k => k[2]))).filter(Boolean).sort();
  if (sel.t && !trips.includes(sel.t)) sel.t = null;
  if (trips.length === 1) sel.t = trips[0];
  show("t", trips.length > 1);
  fillSelect(`${side}_t`, trips, sel.t, v => v, "— vælg —");

  // 4. mærkestrøm
  m = items.filter(it => ok(it, 3));
  let ins;
  if (kind === "col") ins = uniq(m.map(c => c.In));
  else ins = uniq(m.flatMap(r => r.v ? r.v : (r.lab ? [r.lab] : [])));
  ins.sort(cmpNum);
  if (sel.i != null && !ins.includes(sel.i)) sel.i = null;
  if (ins.length === 1) sel.i = ins[0];
  show("i", ins.length > 1 || (ins.length === 1 && ins[0] !== ""));
  // motorværn / termorelæ: listen er indstillingsområder, ikke mærkestrømme
  $(`${side}_row_i`).querySelector("label").textContent =
    /^(TeSys |Integral 63|iC60L MA|NG125L MA)/.test(sel.s) ? "Indstillingsområde" : STEPS[3].label;
  fillSelect(`${side}_i`, ins, sel.i, v => v === "" ? "– (ikke angivet)" : v, "— vælg —");

  // 5. indstilling (Ir / Im …)
  m = items.filter(it => ok(it, 4));
  const xs = uniq(m.map(it => kind === "col" ? it.st : it.ir)).filter(x => kind === "col" || x);
  xs.sort(cmpNum);
  if (sel.x != null && !xs.includes(sel.x)) sel.x = null;
  if (xs.length === 1) sel.x = xs[0];
  show("x", xs.length > 1);
  fillSelect(`${side}_x`, xs, sel.x, v => v === "" ? "Standard / ikke angivet" : v, "— vælg —");

  const ready = sel.s && (perfs.length <= 1 || sel.p || side === "dn") && (trips.length <= 1 || sel.t) && (ins.length <= 1 || sel.i != null) && (xs.length <= 1 || sel.x != null);
  const final = items.filter(it => ok(it, 5));
  $(`${side}_note`).textContent = ready ? "" : "Vælg de resterende felter.";
  return ready ? final : null;
}

// ---------- hovedrender ----------
let upItems = [], dnItems = [];
function render() {
  // spænding
  const volts = uniq(DATA.map(t => t.volt)).sort();
  fillSelect("volt", volts, S.volt || null, v => v, "Alle spændinger");

  const tv = tablesV();
  upItems = tv.flatMap(t => t.cols.map((c, ci) => Object.assign(c, { _t: t, _i: ci })));
  const upFinal = renderSide("up", upItems, "col");

  // downstream: kun rækker i tabeller hvor den valgte upstream findes
  let dnPool = [];
  if (upFinal && upFinal.length) {
    const tabs = new Set(upFinal.map(c => c._t));
    dnPool = [...tabs].flatMap(t => t.rows.map((r, ri) => Object.assign(r, { _t: t, _i: ri })));
  }
  const dnFinal = renderSide("dn", dnPool, "row");
  renderResult(upFinal, dnFinal);
}

function classify(v, t) {
  const raw = (v || "").trim();
  const foot = raw.endsWith("*");
  const val = raw.replace(/\*$/, "");
  if (val === "T") return { kind: "total", foot };
  if (/^\d+(?:[.,]\d+)?$/.test(val)) {
    const n = parseFloat(val.replace(",", "."));
    return { kind: "partial", kA: t.unit === "A" ? n / 1000 : n, raw: val, foot };
  }
  return { kind: "none", foot };
}

function renderResult(upFinal, dnFinal) {
  const out = $("out");
  if (!upFinal || !dnFinal) {
    out.innerHTML = '<p class="hint">Vælg upstream- og downstream-komponent trin for trin – felter med kun én mulighed udfyldes automatisk.</p>';
    return;
  }
  const ik = parseFloat(String($("ik").value).replace(",", "."));
  const hits = [], seen = new Set();
  for (const c of upFinal) for (const r of dnFinal) {
    if (c._t !== r._t) continue;
    const key = c._t.id + ":" + c._i + ":" + r._i;
    if (seen.has(key)) continue;
    seen.add(key);
    hits.push({ t: c._t, c, r });
  }
  if (!hits.length) {
    out.innerHTML = '<p class="hint">Kombinationen findes ikke i de almindelige selektivitetstabeller.</p>';
    renderCasc(out, ik);
    return;
  }
  hits.sort((a, b) => a.t.volt.localeCompare(b.t.volt) || (a.t.src === "2019") - (b.t.src === "2019") || a.t.page - b.t.page);

  out.innerHTML = "";
  const volts = uniq(hits.map(h => h.t.volt));
  if (volts.length > 1) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = `Kombinationen findes i tabeller for ${volts.length} spændinger – vælg „Spænding / net" øverst for at afgrænse.`;
    out.appendChild(p);
  }
  let lastVolt = null;
  for (const { t, c, r } of hits) {
    if (volts.length > 1 && t.volt !== lastVolt) {
      const h = document.createElement("h3");
      h.className = "vhead";
      h.textContent = t.volt;
      out.appendChild(h);
      lastVolt = t.volt;
    }
    const k = classify(t.cells[r._i][c._i], t);
    const div = document.createElement("div");
    div.className = "res " + k.kind;
    let verdict, ikLine = "";
    if (k.kind === "total") {
      verdict = "Total selektivitet";
      if (!isNaN(ik)) ikLine = `<div class="ik okk">✓ Selektiv ved Ik = ${fmt(ik)} kA</div>`;
    } else if (k.kind === "partial") {
      verdict = `Delvis selektivitet – op til ${fmt(k.kA)} kA` + (t.unit === "A" ? ` <span style="font-weight:400">(${fmt(parseFloat(k.raw))} A)</span>` : "");
      if (!isNaN(ik)) ikLine = ik <= k.kA
        ? `<div class="ik okk">✓ Selektiv ved Ik = ${fmt(ik)} kA (≤ ${fmt(k.kA)} kA)</div>`
        : `<div class="ik nok">✗ Ikke selektiv ved Ik = ${fmt(ik)} kA (> ${fmt(k.kA)} kA)</div>`;
    } else {
      verdict = t.ratio ? "Total selektivitet er ikke sikret" : "Ingen selektivitet";
      if (!isNaN(ik)) ikLine = `<div class="ik nok">✗ Ikke selektiv</div>`;
    }
    const P = PDFS[t.src];
    const pdfLink = (pdfAvailable[t.src]
      ? `<a href="${encodeURI(P.file)}#page=${t.page}" target="_blank" rel="noopener">${t.ref} (PDF-side ${t.page})</a>`
      : `side ${t.ref} (PDF-side ${t.page})`) + ` · ${P.name}`;
    const notes = [
      t.src === "2019" ? `<div><b>OBS:</b> Findes kun i 2019-kataloget og er ikke med i 2026-guiden – kontrollér om produktet stadig er aktuelt.</div>` : "",
      k.foot ? `<div><b>OBS:</b> Værdien har en fodnote i kataloget – læs fodnoten på siden.</div>` : "",
      t.ratio ? `<div>Sikring/sikring: total selektivitet kræver, at downstream-sikringen ikke overstiger tabelværdien (IEC 60269). Katalogets værdi „8000" ved 1250 A er tolket som 800 A.</div>` : "",
    ].join("");
    div.innerHTML = `
      <div class="verdict">${verdict}</div>${ikLine}
      <div class="meta">
        <div><b>Upstream i tabellen:</b> ${esc(c.raw)}</div>
        <div><b>Downstream i tabellen:</b> ${esc(r.raw || "–")}${t.ctx ? " · " + esc(t.ctx) : ""}</div>
        <div><b>Tabel:</b> ${esc(t.up)} → ${esc(t.dn)} · ${esc(t.volt)} · værdier i ${t.unit}</div>
        <div><b>Kilde:</b> ${pdfLink}</div>${notes}
      </div>
      ${strip(t, c, r)}`;
    out.appendChild(div);
  }
  renderCasc(out, ik);
}

// ---------- forstærket selektivitet ved kaskade (A-216 – A-245) ----------
// CASC-tabellerne indgår ikke i valgmulighederne; de slås op ud fra det, der er valgt i de almindelige tabeller.
const tripFam = s => /^TM/.test(s) ? "TM" : /^MicroLogic/.test(s) ? "ML" : s;
// Kaskade-tabellerne findes for 220-240, 380-415 og 440 V AC; de almindelige MCCB-tabeller hedder „≤ 440 V AC".
const cascVoltOk = (cv, v) => !v || (/V AC/.test(v) && !/690/.test(v));

function cascColOk(c, sel) {
  const kOk = c.k.some(k => k[0] === sel.s
    && (sel.p == null || !k[1].length || k[1].includes(sel.p))
    && (!sel.t || k[2].includes("") || k[2].some(x => tripFam(x) === tripFam(sel.t))));
  if (!kOk) return false;
  if (sel.i && c.In.length && !c.In.includes(sel.i)) return false;
  const ir = /\bIr\s*(\d+(?:[.,]\d+)?)/.exec(sel.x || "");
  if (ir && c.ir && nums(c.ir)[0] !== parseFloat(ir[1].replace(",", "."))) return false;
  return true;
}
function cascRowOk(r, sel) {
  if (!r.k.some(k => k[0] === sel.s && (sel.p == null || !k[1].length || k[1].includes(sel.p)))) return false;
  if (!sel.i || !r.v) return true;
  if (r.v.includes(sel.i)) return true;
  if (r.rng.length === 2) {           // motorrækker: indstillingsområde, fx 0,1–0,16 A
    const n = nums(sel.i);
    if (n.length >= 2 && n.slice(-2).every((x, j) => x === r.rng[j])) return true;
    if (n.length === 1 && n[0] >= r.rng[0] && n[0] <= r.rng[1]) return true;
  }
  return false;
}
function cascValue(v) {
  const m = /^(\d+(?:[.,]\d+)?|-)\/(\d+(?:[.,]\d+)?)/.exec(v || "");
  if (!m) return null;
  const b = parseFloat(m[2].replace(",", "."));
  const a = m[1] === "-" ? null : parseFloat(m[1].replace(",", "."));
  return { a, b, kind: a == null ? "none" : a >= b ? "total" : "partial" };
}

function renderCasc(out, ik) {
  const res = [], empty = [];
  for (const t of CASC) {
    if (!cascVoltOk(t.volt, S.volt)) continue;
    const cols = t.cols.map((c, i) => [c, i]).filter(([c]) => cascColOk(c, S.up));
    if (!cols.length) continue;
    const rows = t.rows.map((r, i) => [r, i]).filter(([r]) => cascRowOk(r, S.dn));
    const n = res.length;
    for (const [r, ri] of rows) for (const [c, ci] of cols) {
      const v = cascValue(t.cells[ri][ci]);
      if (v) res.push({ t, c, r, v });
    }
    if (rows.length && res.length === n) empty.push(t);
  }
  const P = PDFS["2026"];
  const src = t => pdfAvailable["2026"]
    ? `<a href="${encodeURI(P.file)}#page=${t.page}" target="_blank" rel="noopener">${t.ref}</a>`
    : `${t.ref} (PDF-side ${t.page})`;
  if (!res.length) {
    if (empty.length) {
      const p = document.createElement("p");
      p.className = "note";
      p.innerHTML = `Forstærket selektivitet ved kaskade: kombinationen står i ${uniq(empty.map(src)).join(", ")}, men tabellen angiver ingen værdi for den.`;
      out.appendChild(p);
    }
    return;
  }
  const MAX = 60;
  const lines = res.slice(0, MAX).map(({ t, c, r, v }) => {
    let sel, ikc = "";
    if (v.kind === "total") sel = `<span class="okc">Total – op til ${fmt(v.b)} kA</span>`;
    else if (v.kind === "partial") sel = `<span class="warnc">Op til ${fmt(v.a)} kA</span>`;
    else sel = `<span class="badc">Ingen selektivitet</span>`;
    if (!isNaN(ik)) {
      if (ik > v.b) ikc = `<span class="badc">✗ Ik &gt; ${fmt(v.b)} kA</span>`;
      else if (v.a != null && ik <= v.a) ikc = `<span class="okc">✓ Selektiv</span>`;
      else ikc = `<span class="badc">✗ Ikke selektiv</span>`;
    }
    return `<tr><td>${esc(t.volt)}</td><td>${esc(c.raw)}</td><td>${esc(r.raw)}</td><td>${sel}</td><td>${fmt(v.b)} kA</td>${isNaN(ik) ? "" : `<td>${ikc}</td>`}<td>${src(t)}</td></tr>`;
  }).join("");
  const sec = document.createElement("div");
  sec.className = "casc";
  sec.innerHTML = `
    <h3 class="vhead">Forstærket selektivitet ved kaskade</h3>
    <p class="note" style="margin-top:4px">Gælder kun når de to afbrydere også er i kaskade, dvs. når Ik ved downstream-afbryderen er større end dens egen brydeevne (Icu). Kombinationen kan så være selektiv op til en højere strøm end i de almindelige tabeller, og downstream-afbryderens brydeevne forstærkes. Kilde: „Selectivity enhanced by cascading" i 2026-guiden.</p>
    <div class="strip"><table>
      <tr><th>Spænding</th><th>Upstream</th><th>Downstream</th><th>Selektivitet</th><th>Forstærket brydeevne</th>${isNaN(ik) ? "" : "<th>Ved Ik</th>"}<th>Kilde</th></tr>
      ${lines}
    </table></div>
    ${res.length > MAX ? `<p class="note">Viser ${MAX} af ${res.length} kombinationer – vælg flere felter for at afgrænse.</p>` : ""}`;
  out.appendChild(sec);
}

// rækken for samme upstream-serie/udførelse/udløser på tværs af mærkestrømme
function strip(t, c, r) {
  const sel = S.up;
  const cols = t.cols.map((x, i) => [x, i]).filter(([x]) => colOk(x, sel, 3));
  if (cols.length < 2) return "";
  const lab = x => (x.In || "–") + (x.st ? " / " + x.st : "");
  const head = cols.map(([x, i]) => `<th class="${i === c._i ? "cur" : ""}">${esc(lab(x))}</th>`).join("");
  const body = cols.map(([x, i]) => { const v = t.cells[r._i][i] || ""; return `<td class="${i === c._i ? "cur " : ""}${v.startsWith("T") ? "T" : ""}">${esc(v || "–")}</td>`; }).join("");
  return `<div class="strip"><table><tr><th>Upstream In →</th>${head}</tr><tr><th>Værdi</th>${body}</tr></table></div>`;
}

// ---------- start ----------
buildForm("up");
buildForm("dn");
$("volt").addEventListener("change", e => { S.volt = e.target.value === "\u0000" ? "" : e.target.value; render(); });
$("ik").addEventListener("input", render);
$("reset").addEventListener("click", () => { S.volt = ""; S.up = blank(); S.dn = blank(); $("ik").value = ""; render(); });
render();
