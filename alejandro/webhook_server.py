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

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "alejandro-webhook-2026")
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL_SECONDS", "300"))

granskning_lås = threading.Lock()
server_redo = threading.Event()

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "alejandro-ai-handlaggare"})

@app.route("/webhook/inlamning", methods=["POST"])
def webhook_inlamning():
    secret = request.headers.get("X-Webhook-Secret", "")
    if secret != WEBHOOK_SECRET:
        logger.warning(f"⚠️ Webhook med fel secret")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    inlamning_id = data.get("inlamningId")
    logger.info(f"📨 Webhook mottagen – inlämning #{inlamning_id}")

    def granska():
        if not granskning_lås.acquire(blocking=False):
            granskning_lås.acquire()
        try:
            from main import kör_granskning
            kör_granskning()
        finally:
            granskning_lås.release()

    threading.Thread(target=granska, daemon=True).start()
    return jsonify({"status": "accepted", "inlamningId": inlamning_id}), 202

@app.route("/webhook/granska-alla", methods=["POST"])
def webhook_granska_alla():
    secret = request.headers.get("X-Webhook-Secret", "")
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    def granska():
        with granskning_lås:
            from main import kör_granskning
            kör_granskning()

    threading.Thread(target=granska, daemon=True).start()
    return jsonify({"status": "accepted"}), 202

def bakgrunds_initiering():
    """Körs i bakgrundstråd efter att Flask startat."""
    time.sleep(2)  # Ge Flask tid att starta
    logger.info("🔧 Initierar Alejandro...")

    from main import setup_ai_kolumner, get_ai_handlaggare_id, kör_granskning

    setup_ai_kolumner()
    handlaggare_id = get_ai_handlaggare_id()
    if not handlaggare_id:
        logger.error("❌ Alejandro saknas i databasen. Kör: python setup.py")
        return
    logger.info(f"👤 Alejandro inloggad (ID: {handlaggare_id})")

    # Kör första granskning
    kör_granskning()

    # Backup-polling
    schedule.every(POLLING_INTERVAL).seconds.do(kör_granskning)
    while True:
        schedule.run_pending()
        time.sleep(10)

def main():
    logger.info("=" * 60)
    logger.info("🤖 Alejandro Fuentes Bergström – AI-handläggare startar")
    logger.info("   Webhook-läge + backup-polling")
    logger.info("=" * 60)

    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("❌ ANTHROPIC_API_KEY saknas"); sys.exit(1)
    if not os.getenv("DATABASE_URL"):
        logger.error("❌ DATABASE_URL saknas"); sys.exit(1)

    # Starta bakgrundstråd för initiering
    init_tråd = threading.Thread(target=bakgrunds_initiering, daemon=True)
    init_tråd.start()

    # Starta Flask direkt (svarar på /health med en gång)
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"🌐 Webhook-server lyssnar på port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
