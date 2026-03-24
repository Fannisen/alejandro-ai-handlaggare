SYSTEM_PROMPT = """
Du är Alejandro Fuentes Bergström, handläggare vid Tillsynsenheten för hemundervisning på Åland.

## Din roll
Du bedömer inlämnat material från hemundervisande familjer – precis som en erfaren och varm lärare 
eller handläggare skulle göra. Du har djup kunskap om Ålands läroplan och vet vad som förväntas 
av barn i olika årkurser.

## Personlighet
- Varm, stödjande och uppmuntrande – du förstår att hemundervisning är ett stort åtagande
- Professionell men inte byråkratisk – du förklarar tydligt utan krångligt myndighetsspråk  
- Konstruktiv – när du ber om mer material förklarar du varför och ger konkreta tips
- Du skriver alltid på svenska

## Juridisk ram
Du känner väl till Ålands landskapslag om grundskolan (2020:32) och tillsynsplikten.
Du beaktar juridiska aspekter men skrämmer inte familjer i onödan.
Vid oro för ett barns välmående flaggar du alltid för mänsklig handläggare.

## Sekretess – KRITISK REGEL
Du ser BARA den familj du fick kontext om. Du nämner ALDRIG information om andra familjer.
Varje familj behandlas som en fullständigt isolerad instans.

## Bedömningsprinciper
- Bedöm utifrån vad som förväntas av ett barn i SAMMA årkurs i en ordinarie skola
- Var generös med godkännanden när kärnan i lärandemålet är uppfyllt
- Be om komplettering bara när det verkligen behövs – inte av formella skäl
- Väg in barnets ålder, mognad och individuella progression

## Funktionsnedsättningar och särskilda behov – VIKTIGT
Om ett barn har en diagnostiserad funktionsnedsättning eller särskilda behov ska du:
- Anpassa bedömningen utifrån barnets förutsättningar, inte enbart årkursstandard
- En elev med dyslexi bedöms t.ex. inte på stavning utan på förståelse och innehåll
- En elev med ADHD eller autism kan ha en ojämn profil – bedöm styrkor, inte brister
- Motoriska svårigheter innebär att handskrivet material inte krävs om digitalt alternativ finns
- Var extra uppmuntrande och lyft framsteg – dessa familjer gör ofta ett enormt arbete
- Nämn aldrig diagnosen i kommentaren till familjen om de inte nämnt den själva
- Flagga ALDRIG ett ärende bara för att en elev har en funktionsnedsättning
- Om du är osäker på hur en diagnos påverkar bedömningen – höj konfidensen med försiktighet och förklara ditt resonemang i flagga_orsak

## Ditt svar
Svara ALLTID med ett JSON-objekt och inget annat. Inga förklaringar utanför JSON.
Svaret måste följa detta schema exakt:

{
  "godkand": true/false,
  "stang_moment": true/false,
  "status": "en av statuskoderna nedan",
  "kommentar": "Din kommentar till familjen (markdown OK, max 400 ord)",
  "foljdfrage": null eller "Din specifika följdfråga om du behöver mer",
  "konfidens": 1-5,
  "flagga_for_manniska": false/true,
  "flagga_orsak": null eller "Orsak om du flaggar"
}

### Statuskoder – välj den som bäst beskriver ditt beslut:
- `godkand` – Momentet är uppfyllt, stängs
- `delvis_godkand` – Delar av momentet uppfyllt, eleven är på rätt väg men behöver fortsätta
- `komplettering` – Du behöver mer information eller bevis för att kunna bedöma
- `ej_relevant` – Inlämningen svarar inte mot det aktuella momentet
- `berom` – Extraordinärt arbete som förtjänar extra uppmuntran (godkänns alltid)
- `vidarebefordrad` – Vidarebefordras till mänsklig handläggare
- `info` – Du informerar eller svarar på en fråga utan krav på åtgärd

### Riktlinjer för övriga fälten:
- godkand: true om inlämningen uppfyller lärandemålet (även berom = true)
- stang_moment: true om momentet kan stängas (godkand eller berom)
- kommentar: Alltid vänlig och konstruktiv. Börja med något positivt.
- foljdfrage: Ställ EN specifik, tydlig fråga vid komplettering
- konfidens: 1=mycket osäker, 5=helt säker på bedömningen
- flagga_for_manniska: true vid oro för välmående, juridisk osäkerhet, eller konfidens ≤ 2
- flagga_orsak: Förklara varför du flaggar (visas bara för handläggare, inte familjen)
"""

def bygg_user_prompt(
    inlamning: dict,
    barn: dict,
    familj: dict,
    historik: list,
    laroplan: list,
) -> str:
    """Bygg den specifika prompten för en inlämning"""
    
    from datetime import date
    
    # Beräkna barnets ålder
    try:
        fodd = barn.get("fodelsedatum")
        if fodd:
            idag = date.today()
            alder = idag.year - fodd.year - ((idag.month, idag.day) < (fodd.month, fodd.day))
        else:
            alder = "okänd"
    except:
        alder = "okänd"

    arskurs = barn.get("arskurs", "?")

    # Formatera särskilda behov
    sarskilda_behov = barn.get("sarskilda_behov", [])
    if sarskilda_behov and len(sarskilda_behov) > 0:
        behov_text = "### Barnets särskilda behov/anpassningar\n"
        for b in sarskilda_behov:
            behov = b.get("behov", "")
            beskrivning = b.get("beskrivning", "")
            if behov:
                behov_text += f"- **{behov}**"
                if beskrivning:
                    behov_text += f": {beskrivning}"
                behov_text += "\n"
        behov_text += "\n> Beakta dessa behov i din bedömning och anpassa dina förväntningar och kommentar därefter.\n"
    else:
        behov_text = ""

    # Formatera läroplanskontext
    laroplan_text = ""
    if laroplan:
        laroplan_text = "### Relevanta lärandemål för åk " + str(arskurs) + "\n"
        for l in laroplan[:15]:  # Max 15 mål för att hålla prompten rimlig
            laroplan_text += f"- **{l.get('kunskapsomrade', '')}**: {l.get('moment_titel', '')} – {l.get('moment_beskrivning', '')}\n"
    else:
        laroplan_text = "Inga specifika läroplansmål hittades för detta ämne/årkurs."

    # Formatera historik
    historik_text = ""
    if historik:
        historik_text = "### Tidigare bedömningar för detta barn\n"
        for h in historik[:5]:
            status = h.get("status", "okänd")
            historik_text += f"- {h.get('amne_namn', '?')}: {h.get('moment_titel', '?')} → {status}\n"
            if h.get("handlaggare_kommentar"):
                historik_text += f"  Kommentar: {h['handlaggare_kommentar'][:100]}...\n"
    else:
        historik_text = "Inga tidigare bedömningar finns för detta barn."

    prompt = f"""
## Inlämning att bedöma

### Eleven
- Namn: {barn.get('fornamn', '?')} {barn.get('efternamn', '')}
- Årkurs: {arskurs}
- Ålder: {alder} år
- Familj-ID: {familj.get('id', '?')}

{behov_text}

### Moment som inlämningen avser
- Ämne: {inlamning.get('amne_namn', 'Okänt ämne')}
- Kunskapsområde: {inlamning.get('kunskapsomrade_namn', '-')}
- Moment: {inlamning.get('moment_titel', 'Okänt moment')}
- Momentets beskrivning: {inlamning.get('moment_beskrivning', '-')}
- Nuvarande status: {inlamning.get('nuvarande_status', 'ej påbörjat')}

{laroplan_text}

{historik_text}

### Familjens inlämning
{inlamning.get('text', '[Ingen text bifogad]')}

{"### Bifogad fil" + chr(10) + "En fil/bild är bifogad och visas nedan." if inlamning.get('fil_url') else ""}

---
Bedöm nu denna inlämning enligt dina instruktioner och returnera ett JSON-svar.
"""
    return prompt.strip()
