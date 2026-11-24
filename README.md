# Selektivitetsbuddy

Web-app til opslag af selektivitet mellem to beskyttelseskomponenter (upstream/downstream) ud fra
Schneider Electric „Complementary technical information – Low Voltage" (katalog 2019), tabellerne A-15 – A-152.

Resultatet vises som **total selektivitet** (T), **delvis selektivitet op til X kA** eller **ingen selektivitet**,
med henvisning til katalogsiden.

Appen er én statisk fil: `index.html`. Læg `Schneider - Selektivitetstabeller.pdf` ved siden af den, hvis
kildehenvisningerne skal være klikbare links (PDF'en er ikke med i repo'et).

## Genopbyg data fra PDF

Kræver Python med PyMuPDF (`pip install pymupdf`).

```
python tools/parse.py "Schneider - Selektivitetstabeller.pdf" all.json
python tools/build.py all.json index.html tools/app_template.html
```

## Ansvarsfraskrivelse

Data er udtrukket automatisk og kan indeholde fejl. Kataloget er den gældende kilde.
Værktøjet er ikke udgivet af eller tilknyttet Schneider Electric.
