# 🚗 Přepis Vozidla – Automatické vyplnění formulářů

Lokální webová aplikace pro automatické vyplňování žádostí o přepis vozidla.

## Požadavky

- Python 3.9+
- pip

## Instalace

```bash
pip install flask pypdf requests
```

## Spuštění

```bash
python app.py
```

Pak otevřete prohlížeč na: **http://localhost:5050**

## Co aplikace dělá

1. **Zadáte prodávajícího a kupujícího** – fyzická nebo právnická osoba
2. **IČO lookup** – zadáte IČO a aplikace automaticky načte název, adresu a PSČ z ARES (registr MF ČR)
3. **Zadáte údaje o vozidle** – VIN, RZ, značka, barva atd.
4. **Vygenerujete PDF** – obě žádosti jsou vyplněny automaticky
5. **Stáhnete nebo vytisknete** přímo z prohlížeče

## Generované dokumenty

- `Žádost o zápis změny vlastníka nebo provozovatele silničního vozidla`
- `Žádost o zápis silničního vozidla do registru silničních vozidel`

## Struktura projektu

```
prepis_app/
├── app.py              # Flask backend + PDF logika
├── templates/
│   └── index.html      # Webové rozhraní
├── pdfs/
│   ├── zmeny.pdf       # Šablona žádosti o změnu vlastníka
│   └── zapis.pdf       # Šablona žádosti o zápis
└── output/             # Vygenerované PDFs (vytvoří se automaticky)
```

## Další rozvoj (Phase 2)

- 📷 Skenování dokumentů kamerou → Claude Vision API extrahuje data
- 📄 Automatické načtení COC listu / Osvědčení o registraci
- 🖨️ Přímý tisk na připojené tiskárně

## API klíč pro skenování

Pro funkci skenování dokumentů budete potřebovat:
1. Anthropic API klíč z https://console.anthropic.com
2. Přidat do app.py: `ANTHROPIC_API_KEY = "sk-ant-..."`
