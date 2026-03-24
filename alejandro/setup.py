"""
Engångsskript: Sätter upp Alejandro i databasen och lägger till nödvändiga kolumner.
Kör INNAN main.py för första gången.

Kör: python setup.py
"""
import os
import sys
from loguru import logger
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from utils.db import get_connection, setup_ai_kolumner

def skapa_alejandro():
    """Skapa AI-handläggarens användarkonto"""
    email = os.getenv("AI_HANDLAGGARE_EMAIL", "alejandro@hemundervisning.ax")
    namn = os.getenv("AI_HANDLAGGARE_NAMN", "Alejandro Fuentes Bergström")
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Kolla om användaren redan finns
            cur.execute("SELECT id FROM anvandare WHERE email = %s", (email,))
            existing = cur.fetchone()
            
            if existing:
                logger.info(f"✅ Alejandro finns redan (ID: {existing[0]})")
                return existing[0]
            
            # Skapa användare med ett starkt lösenord för API-åtkomst
            import secrets
            ai_losenord = os.getenv("AI_LOSENORD", secrets.token_urlsafe(32))
            # Spara lösenordet i .env om det inte finns
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            env_content = open(env_path).read() if os.path.exists(env_path) else ""
            if "AI_LOSENORD=" not in env_content:
                with open(env_path, "a") as f:
                    f.write(f"\nAI_LOSENORD={ai_losenord}\n")
                logger.info(f"✅ AI_LOSENORD sparat i .env")
            else:
                # Hämta befintligt lösenord
                for line in env_content.split("\n"):
                    if line.startswith("AI_LOSENORD="):
                        ai_losenord = line.split("=", 1)[1].strip()
            
            # Använd BCrypt via psql-funktionen om tillgänglig, annars plain
            try:
                import bcrypt
                losenord_hash = bcrypt.hashpw(ai_losenord.encode(), bcrypt.gensalt()).decode()
            except ImportError:
                losenord_hash = ai_losenord  # Fallback
                logger.warning("⚠️  bcrypt ej installerat - kör: pip install bcrypt")

            cur.execute("""
                INSERT INTO anvandare 
                    (namn, email, roll, aktiv, losenord_hash, skapad_at)
                VALUES (%s, %s, 'handlaggare', true, %s, NOW())
                RETURNING id
            """, (namn, email, losenord_hash))
            ny_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"✅ Alejandro skapad (ID: {ny_id})")
        return ny_id

def verifiera_setup():
    """Verifiera att allt är på plats"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Kolla inlamningar-tabellen
            cur.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'inlamningar' 
                AND column_name IN ('ai_granskad', 'ai_flaggad', 'ai_godkand', 'ai_konfidens')
            """)
            kolumner = [r[0] for r in cur.fetchall()]
            logger.info(f"✅ AI-kolumner i inlamningar: {kolumner}")
            
            # Kolla tabeller
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tabeller = [r[0] for r in cur.fetchall()]
            logger.info(f"📊 Tabeller i databasen: {', '.join(tabeller)}")

def main():
    logger.info("🔧 Alejandro Setup")
    logger.info("=" * 40)
    
    if not os.getenv("DATABASE_URL"):
        logger.error("❌ DATABASE_URL saknas i .env")
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("⚠️  ANTHROPIC_API_KEY saknas – kom ihåg att lägga till den i .env")
    
    logger.info("1. Lägger till AI-kolumner i databasen...")
    setup_ai_kolumner()
    
    logger.info("2. Skapar Alejandro som användare...")
    ai_id = skapa_alejandro()
    
    logger.info("3. Verifierar setup...")
    verifiera_setup()
    
    logger.info("=" * 40)
    logger.info("✅ Setup klar! Kör nu: python main.py")

if __name__ == "__main__":
    main()
