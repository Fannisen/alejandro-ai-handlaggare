"""
Alejandro webhook-server
Lyssnar på POST /webhook/inlamning när en ny inlämning skapas.
Kör också polling var 5 minut som backup.
"""
import os
import sys
import threading
import time
import logging
import schedule
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Webhook-secret för säkerhet (samma måste sättas i backend)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "alejandro-webhook-2026")
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL_SECONDS", "300"))  # 5 min backup-polling

# Import från main.py
from main import (
    kör_granskning,
    behandla_en_inlamning,
    get_ai_handlaggare_id,
    setup_ai_kolumner,
)

# Lås för att undvika parallella granskningar
granskning_lås = threading.Lock()

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "alejandro-ai-handlaggare"})

@app.route("/webhook/inlamning", methods=["POST"])
def webhook_inlamning():
    """Kallas av backenden direkt när en ny inlämning sparas."""
    # Verifiera secret
    secret = request.headers.get("X-Webhook-Secret", "")
    if secret != WEBHOOK_SECRET:
        logger.warning(f"⚠️ Webhook med fel secret: {secret[:20]}")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    inlamning_id = data.get("inlamningId")
    logger.info(f"📨 Webhook mottagen – inlämning #{inlamning_id}")

    # Kör granskning i bakgrundstråd så webhook svarar snabbt
    def granska():
        if not granskning_lås.acquire(blocking=False):
            logger.info("⏳ Granskning redan pågår – väntar...")
            granskning_lås.acquire()
        try:
            kör_granskning()
        finally:
            granskning_lås.release()

    threading.Thread(target=granska, daemon=True).start()
    return jsonify({"status": "accepted", "inlamningId": inlamning_id}), 202

@app.route("/webhook/granska-alla", methods=["POST"])
def webhook_granska_alla():
    """Manuell trigger – granska alla väntande inlämningar."""
    secret = request.headers.get("X-Webhook-Secret", "")
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    def granska():
        with granskning_lås:
            kör_granskning()

    threading.Thread(target=granska, daemon=True).start()
    return jsonify({"status": "accepted"}), 202

def backup_polling():
    """Polling var 5 minut som backup om webhook missar något."""
    logger.info(f"⏰ Backup-polling var {POLLING_INTERVAL // 60} minut(er)")
    schedule.every(POLLING_INTERVAL).seconds.do(kör_granskning)
    while True:
        schedule.run_pending()
        time.sleep(10)

def main():
    logger.info("=" * 60)
    logger.info("🤖 Alejandro Fuentes Bergström – AI-handläggare startar")
    logger.info("   Tillsynsenheten för hemundervisning på Åland")
    logger.info("   Läge: Webhook + backup-polling")
    logger.info("=" * 60)

    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("❌ ANTHROPIC_API_KEY saknas")
        sys.exit(1)
    if not os.getenv("DATABASE_URL"):
        logger.error("❌ DATABASE_URL saknas")
        sys.exit(1)

    # Setup databas
    logger.info("🔧 Kontrollerar databasstruktur...")
    setup_ai_kolumner()

    handlaggare_id = get_ai_handlaggare_id()
    if not handlaggare_id:
        logger.error("❌ Alejandro saknas i databasen. Kör: python setup.py")
        sys.exit(1)
    logger.info(f"👤 Alejandro inloggad (ID: {handlaggare_id})")

    # Kör granskning direkt vid start
    kör_granskning()

    # Starta backup-polling i bakgrundstråd
    polling_tråd = threading.Thread(target=backup_polling, daemon=True)
    polling_tråd.start()

    # Starta Flask webhook-server
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"🌐 Webhook-server lyssnar på port {port}")
    logger.info(f"   POST /webhook/inlamning  – ny inlämning")
    logger.info(f"   GET  /health             – hälsokontroll")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
