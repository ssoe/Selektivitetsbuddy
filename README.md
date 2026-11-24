# Selektivitetsbuddy

Web-app til opslag af selektivitet mellem to beskyttelseskomponenter (upstream/downstream) ud fra
Schneider Electric „Selectivity, Cascading and Coordination Guide" (september 2026). iDPN-tabeller, der ikke
længere er med i 2026-guiden, er bevaret fra „Complementary technical information" (2019) og markeret i appen.

Resultatet vises som **total selektivitet** (T), **delvis selektivitet op til X kA** eller **ingen selektivitet**,
med henvisning til katalogsiden.

Appen er én statisk fil: `index.html`. Læg `Selektivitetstabeller 2026.pdf` (og evt.
`Schneider - Selektivitetstabeller.pdf`) ved siden af den, hvis kildehenvisningerne skal være klikbare links
(PDF'erne er ikke med i repo'et).

## Genopbyg data fra PDF

Kræver Python med PyMuPDF (`pip install pymupdf`).

```
python tools/parse.py "Selektivitetstabeller 2026.pdf" new.json "25-150,152-184,190-199"
python tools/parse.py "Schneider - Selektivitetstabeller.pdf" old.json
python tools/build.py new.json old.json index.html tools/app_template.html
```

`tools/compare2.py old.json new.json` lister forskelle mellem de to kataloger.

### Filer i `tools/`

- `parse.py` – læser tabellerne ud af PDF'en (tekstpositioner og tegnede linjer).
- `normalize.py` – oversætter katalogets mange stavemåder til faste felter: serie, udførelse
  (fx H1/H2, N/H/L), udløser/kurve, In og indstilling (Ir/Im).
- `build.py` – samler data og indsætter dem sammen med `app.js` i `app_template.html` → `index.html`.
- `app.js` – app-logikken (trinvise valg og opslag).

## Ansvarsfraskrivelse

Data er udtrukket automatisk og kan indeholde fejl. Kataloget er den gældende kilde.
Værktøjet er ikke udgivet af eller tilknyttet Schneider Electric.
