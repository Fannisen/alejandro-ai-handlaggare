# 🤖 Alejandro Fuentes Bergström – AI-Handläggare

AI-driven handläggare för hemundervisning på Åland.
Kopplar mot Railway PostgreSQL och Claude API för automatisk bedömning av inlämningar.

---

## Snabbstart (5 minuter)

### 1. Installera Python-beroenden
```bash
pip install -r requirements.txt
```

### 2. Skapa .env-fil
```bash
copy .env.example .env
```
Öppna `.env` och fyll i din Anthropic API-nyckel:
```
ANTHROPIC_API_KEY=sk-ant-...
```
DATABASE_URL är redan ifylld med Railway-URL:en.

### 3. Kör setup (en gång)
```bash
python setup.py
```
Detta:
- Lägger till AI-kolumner i inlamningar-tabellen
- Skapar Alejandros användarkonto i databasen

### 4. Starta Alejandro
```bash
python main.py
```

---

## Vad händer när det körs?

1. Var 5:e minut kollar Alejandro om det finns nya inlämningar
2. För varje oinläst inlämning hämtar den:
   - Barnets profil och årkurs
   - Familjens kontext (BARA den aktuella familjen)
   - Historik av tidigare bedömningar
   - Relevanta läroplansmål för barnets årkurs
3. Skickar allt till Claude (claude-opus-4-5) med strukturerad prompt
4. Sparar svaret i databasen:
   - Kommentar till familjen
   - Godkänd/ej godkänd
   - Stänger momentet om godkänt
   - Flaggar för mänsklig handläggare om osäkert

---

## Säkerhetsmekanismer

- **Konfidens ≤ 2/5** → automatisk flaggning för mänsklig granskning
- **Oro för välmående** → flaggas alltid
- **Familjeisolering** → SQL-frågor filtrerar alltid på familj_id
- **Loggning** → alla beslut loggas i `logs/alejandro.log`

---

## Filer

```
alejandro/
├── main.py              # Huvudloop (kör denna)
├── setup.py             # Engångssetup
├── requirements.txt     # Python-paket
├── .env                 # Din konfiguration (skapa från .env.example)
├── prompts/
│   └── system.py        # Alejandros personlighet och prompt
├── utils/
│   ├── db.py            # All databaslogik
│   └── claude_api.py    # Anthropic API-integration
└── logs/
    └── alejandro.log    # Loggfil
```

---

## Hämta Anthropic API-nyckel

1. Gå till https://console.anthropic.com
2. Skapa ett konto / logga in
3. Gå till "API Keys" → "Create Key"
4. Klistra in i `.env` som `ANTHROPIC_API_KEY=sk-ant-...`

Kostnad: ~$0.015 per bedömning (claude-opus-4-5)

---

## Vanliga frågor

**Hur ändrar jag hur ofta den kollar?**
Ändra `POLLING_INTERVAL_SECONDS=300` i `.env` (300 = 5 minuter)

**Hur ser jag vad Alejandro har gjort?**
Titta i e-portföljens handläggarvy – kommentarerna syns under Alejandros namn.

**Vad händer med bilder?**
Om en familj laddar upp en bild skickas den till Claude Vision för visuell bedömning.

**Kan jag ångra en bedömning?**
Ja – gå in i e-portföljens admin och ändra manuellt. Alejandros beslut är alltid överskrivbara.
