"""
Alejandro Fuentes Bergström – AI-handläggare för hemundervisning på Åland
Huvudloop: Lyssnar på nya inlämningar och bedömer dem automatiskt.

Kör: python main.py
"""
import os
import sys
import time
import schedule
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# Lägg till projektmappen i path
sys.path.insert(0, os.path.dirname(__file__))

from utils.db import (
    get_connection,
    get_ai_handlaggare_id,
    get_ogranskade_inlamningar,
    get_familjkontext,
    get_barn_historik,
    get_laroplan_for_arskurs,
    spara_ai_svar,
    setup_ai_kolumner,
)
from utils.claude_api import bedom_inlamning

# Konfigurera loggning
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger.remove()
logger.add(sys.stdout, level=LOG_LEVEL, colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/alejandro.log", rotation="10 MB", retention="30 days", level="DEBUG")

KONFIDENS_TROSKEL = int(os.getenv("KONFIDENS_TROSKEL", "3"))
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL_SECONDS", "300"))

def behandla_en_inlamning(inlamning: dict, handlaggare_id: int):
    """Behandla en enskild inlämning med AI-bedömning"""
    
    inlamning_id = inlamning["id"]
    barn_id = inlamning["barn_id"]
    familj_id = inlamning["familj_id"]
    arskurs = inlamning["arskurs"]
    amne_id = inlamning.get("amne_id")
    
    barn_namn = f"{inlamning.get('barn_fornamn', '?')} {inlamning.get('barn_efternamn', '')}"
    logger.info(f"🔍 Behandlar inlämning #{inlamning_id} | {barn_namn} (åk {arskurs}) | {inlamning.get('amne_namn', '?')}: {inlamning.get('moment_titel', '?')}")
    
    # Hämta kontext
    familjekontext = get_familjkontext(familj_id)
    historik = get_barn_historik(barn_id)
    laroplan = get_laroplan_for_arskurs(arskurs, amne_id)
    
    # Hitta barnets data
    barn_list = familjekontext.get("barn", [])
    barn_match = next((b for b in barn_list if b.get("id") == barn_id), None)
    if barn_match:
        barn = dict(barn_match)
    else:
        # Fallback: bygg barn-dict från inlämningens data
        barn = {
            "id": barn_id,
            "fornamn": inlamning.get("barn_fornamn", "?"),
            "efternamn": inlamning.get("barn_efternamn", ""),
            "arskurs": inlamning.get("arskurs", 1),
            "fodelsedatum": inlamning.get("fodelsedatum"),
            "sarskilda_behov": [],
        }
    
    # Kolla om reflektionen eller filen innehåller material Alejandro inte klarar
    from utils.claude_api import analysera_reflektion_for_lankar, analysera_filtyp_kan_ej_hanteras
    
    lank_check = analysera_reflektion_for_lankar(inlamning.get("text", "") or "")
    filtyp_check = analysera_filtyp_kan_ej_hanteras(
        inlamning.get("fil_typ", "") or "",
        inlamning.get("fil_url", "") or ""
    )
    
    if lank_check["flagga"] or filtyp_check["flagga"]:
        orsak = lank_check["orsak"] or filtyp_check["orsak"]
        logger.warning(f"🚩 Flaggar direkt – kan ej hantera: {orsak}")
        spara_ai_svar(
            inlamning_id=inlamning["id"],
            barn_id=inlamning["barn_id"],
            moment_id=inlamning["moment_id"],
            familj_id=inlamning["familj_id"],
            handlaggare_id=handlaggare_id,
            kommentar=f"Tack för din inlämning! Den innehåller material (t.ex. video, ljud eller externa länkar) som behöver granskas av en handläggare. Vi återkommer till dig inom kort.",
            godkand=False,
            stang_moment=False,
            foljdfråga=None,
            konfidens=5,
            flaggad=True,
        )
        # Uppdatera flagga_orsak separat
        from utils.db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE inlamningar SET ai_flaggad = true WHERE id = %s",
                    (inlamning["id"],)
                )
            conn.commit()
        return True

    # Lägg till barn_id och moment_id i inlamning för filnedladdning via rätt endpoint
    inlamning_med_ids = dict(inlamning)
    inlamning_med_ids["_barn_id_for_fil"] = barn_id
    inlamning_med_ids["_moment_id_for_fil"] = inlamning["moment_id"]

    # Fråga Claude
    svar = bedom_inlamning(
        inlamning=inlamning_med_ids,
        barn=barn,
        familj=familjekontext["familj"],
        historik=historik,
        laroplan=laroplan,
    )
    
    if not svar:
        logger.error(f"❌ Fick inget svar från Claude för inlämning #{inlamning_id}")
        return False

    # Hantera tuple-svar (fil kunde inte laddas)
    if isinstance(svar, tuple):
        fil_ej_laddad = svar[1] if len(svar) > 1 else False
        if fil_ej_laddad:
            logger.warning("🚩 Fil kunde inte laddas – flaggar till mänsklig handläggare")
            spara_ai_svar(
                inlamning_id=inlamning_id,
                barn_id=barn_id,
                moment_id=inlamning["moment_id"],
                familj_id=familj_id,
                handlaggare_id=handlaggare_id,
                kommentar="Tack för er inlämning! Den bifogade filen kunde tyvärr inte öppnas av vårt system just nu. En handläggare kommer att granska ärendet manuellt och återkommer till er inom kort.",
                godkand=False,
                stang_moment=False,
                foljdfråga=None,
                konfidens=5,
                flaggad=True,
                ai_status="vidarebefordrad",
            )
            return True
        logger.error(f"❌ Oväntat svar-format: tuple = {str(svar)[:200]}")
        return False

    # Säkerställ att svar är en dict
    if not isinstance(svar, dict):
        logger.error(f"❌ Oväntat svar-format: {type(svar).__name__} = {str(svar)[:200]}")
        return False

    # Validera svar
    godkand = bool(svar.get("godkand", False))
    stang_moment = bool(svar.get("stang_moment", False))
    kommentar = svar.get("kommentar", "Bedömning genomförd.")
    foljdfrage = svar.get("foljdfrage") or svar.get("foljdfråga")
    konfidens = int(svar.get("konfidens", 3))
    flaggad = bool(svar.get("flagga_for_manniska", False))
    flagga_orsak = svar.get("flagga_orsak")

    # Automatisk flaggning vid låg konfidens
    if konfidens <= 2 and not flaggad:
        flaggad = True
        flagga_orsak = f"Låg konfidens ({konfidens}/5) – kräver mänsklig granskning"
        logger.warning(f"⚠️  Flaggar inlämning #{inlamning_id} pga låg konfidens")

    # Logga beslut
    beslut_emoji = "✅" if godkand else ("❓" if foljdfrage else "⚠️")
    logger.info(f"{beslut_emoji} Beslut: godkänd={godkand}, stänger={stang_moment}, konfidens={konfidens}/5, flaggad={flaggad}")
    if flagga_orsak:
        logger.warning(f"   Flagga: {flagga_orsak}")
    logger.info(f"   Kommentar: {kommentar[:120]}...")

    # Spara till databasen
    spara_ai_svar(
        inlamning_id=inlamning_id,
        barn_id=barn_id,
        moment_id=inlamning["moment_id"],
        familj_id=familj_id,
        handlaggare_id=handlaggare_id,
        kommentar=kommentar,
        godkand=godkand,
        stang_moment=stang_moment,
        foljdfråga=foljdfrage,
        konfidens=konfidens,
        flaggad=flaggad,
        ai_status=svar.get("status") if isinstance(svar, dict) else None,
    )
    
    return True

_granskning_pagar = False

def kör_granskning():
    global _granskning_pagar
    if _granskning_pagar:
        logger.info("⏳ Granskning pågår redan – hoppar över")
        return
    _granskning_pagar = True
    try:
        _kör_granskning_intern()
    finally:
        _granskning_pagar = False

def _kör_granskning_intern():
    """Huvudfunktion – körs enligt schema"""
    logger.info("🔄 Startar granskningscykel...")
    
    handlaggare_id = get_ai_handlaggare_id()
    if not handlaggare_id:
        logger.error("❌ Alejandro saknas i databasen! Kör: python setup.py")
        return

    inlamningar = get_ogranskade_inlamningar()
    
    if not inlamningar:
        return
    
    logger.info(f"📬 Hittade {len(inlamningar)} inlämning(ar) att granska")
    
    behandlade = 0
    fel = 0
    for inlamning in inlamningar:
        try:
            success = behandla_en_inlamning(dict(inlamning), handlaggare_id)
            if success:
                behandlade += 1
            else:
                fel += 1
            # Liten paus för att inte hammra API:et
            time.sleep(2)
        except Exception as e:
            logger.error(f"Oväntat fel vid behandling: {e}")
            fel += 1
    
    logger.info(f"✅ Klar: {behandlade} behandlade, {fel} fel")

def main():
    logger.info("=" * 60)
    logger.info("🤖 Alejandro Fuentes Bergström – AI-handläggare startar")
    logger.info("   Tillsynsenheten för hemundervisning på Åland")
    logger.info("=" * 60)
    
    # Verifiera miljövariabler
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("❌ ANTHROPIC_API_KEY saknas i .env")
        sys.exit(1)
    if not os.getenv("DATABASE_URL"):
        logger.error("❌ DATABASE_URL saknas i .env")
        sys.exit(1)

    # Setup
    logger.info("🔧 Kontrollerar databasstruktur...")
    setup_ai_kolumner()
    
    handlaggare_id = get_ai_handlaggare_id()
    if not handlaggare_id:
        logger.error("❌ AI-handläggaren finns inte i databasen. Kör: python setup.py")
        sys.exit(1)
    logger.info(f"👤 Alejandro inloggad (ID: {handlaggare_id})")
    
    # Kör direkt vid start
    kör_granskning()
    
    # Schema: kör var N:e sekund
    interval_min = POLLING_INTERVAL // 60
    logger.info(f"⏰ Schemalägger granskning var {interval_min} minut(er)")
    schedule.every(POLLING_INTERVAL).seconds.do(kör_granskning)
    
    logger.info("🟢 Lyssnar på nya inlämningar... (Ctrl+C eller skriv 'q' + Enter för att avsluta)")

    import threading

    stopp = threading.Event()

    def lyssna_pa_tangentbord():
        while not stopp.is_set():
            try:
                rad = input()
                if rad.strip().lower() in ('q', 'quit', 'exit', 'stopp', 'avsluta'):
                    logger.info("👋 Alejandro avslutar. Hej då!")
                    stopp.set()
            except EOFError:
                break

    t = threading.Thread(target=lyssna_pa_tangentbord, daemon=True)
    t.start()

    try:
        while not stopp.is_set():
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Alejandro avslutar. Hej då!")
    finally:
        stopp.set()

if __name__ == "__main__":
    main()
