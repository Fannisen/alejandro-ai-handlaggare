"""
Databashantering för Alejandro AI-handläggare
Kolumnnamn verifierade mot faktisk databasstruktur 2025-03-23
"""
import os
import psycopg2
import psycopg2.extras
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(url, options="-c client_encoding=UTF8")
    return conn

def get_ai_handlaggare_id() -> int | None:
    email = os.getenv("AI_HANDLAGGARE_EMAIL", "alejandro@hemundervisning.ax")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM anvandare WHERE email = %s AND aktiv = true", (email,))
            row = cur.fetchone()
            return row["id"] if row else None

def get_ogranskade_inlamningar() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    i.id,
                    i.barn_id,
                    i.moment_id,
                    i.reflektion        AS text,
                    i.lagrad_path       AS fil_url,
                    i.filtyp            AS fil_typ,
                    i.uppladdad_at      AS skapad_at,
                    b.fornamn           AS barn_fornamn,
                    b.efternamn         AS barn_efternamn,
                    b.arskurs,
                    b.fodelsedatum,
                    b.familj_id,
                    m.namn              AS moment_titel,
                    m.beskrivning       AS moment_beskrivning,
                    a.id                AS amne_id,
                    a.namn              AS amne_namn,
                    k.namn              AS kunskapsomrade_namn,
                    bms.status          AS nuvarande_status
                FROM inlamningar i
                JOIN barn b           ON b.id = i.barn_id
                JOIN moment m         ON m.id = i.moment_id
                LEFT JOIN kunskapsomraden k ON k.id = m.omrade_id
                LEFT JOIN amnen a           ON a.id = k.amne_id
                LEFT JOIN barn_moment_status bms
                    ON bms.barn_id = i.barn_id AND bms.moment_id = i.moment_id
                WHERE i.ai_granskad = false
                  AND i.ai_flaggad  = false
                ORDER BY i.uppladdad_at ASC
                LIMIT 10
            """)
            return cur.fetchall() or []

def get_familjkontext(familj_id: int) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, namn, kontakt_email, status
                FROM familjer WHERE id = %s
            """, (familj_id,))
            familj = cur.fetchone()

            cur.execute("""
                SELECT
                    b.id, b.fornamn, b.efternamn, b.arskurs, b.fodelsedatum,
                    COALESCE(
                        (SELECT json_agg(row_to_json(bsb))
                         FROM barn_sarskilda_behov bsb
                         WHERE bsb.barn_id = b.id),
                        '[]'::json
                    ) AS sarskilda_behov
                FROM barn b
                WHERE b.familj_id = %s
                  AND b.hemundervisning_avbruten = false
            """, (familj_id,))
            barn = cur.fetchall() or []

            cur.execute("""
                SELECT a.namn, a.email
                FROM handlaggare_tilldelningar ht
                JOIN anvandare a ON a.id = ht.handlaggare_id
                WHERE ht.familj_id = %s AND ht.aktiv = true
            """, (familj_id,))
            handlaggare = cur.fetchall() or []

            return {
                "familj":      dict(familj) if familj else {},
                "barn":        [dict(b) for b in barn],
                "handlaggare": [dict(h) for h in handlaggare],
            }

def get_barn_historik(barn_id: int, limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    i.reflektion        AS inlamning_text,
                    i.uppladdad_at      AS skapad_at,
                    m.namn              AS moment_titel,
                    a.namn              AS amne_namn,
                    bms.status,
                    hk.kommentar        AS handlaggare_kommentar
                FROM inlamningar i
                JOIN moment m ON m.id = i.moment_id
                LEFT JOIN kunskapsomraden k ON k.id = m.omrade_id
                LEFT JOIN amnen a           ON a.id = k.amne_id
                LEFT JOIN barn_moment_status bms
                    ON bms.barn_id = i.barn_id AND bms.moment_id = i.moment_id
                LEFT JOIN handlaggare_kommentarer hk
                    ON hk.barn_id = i.barn_id AND hk.moment_id = i.moment_id
                WHERE i.barn_id = %s
                  AND i.ai_granskad = true
                ORDER BY i.uppladdad_at DESC
                LIMIT %s
            """, (barn_id, limit))
            return cur.fetchall() or []

def get_laroplan_for_arskurs(arskurs: int, amne_id: int = None) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = """
                SELECT
                    a.namn  AS amne_namn,
                    k.namn  AS kunskapsomrade,
                    m.namn  AS moment_titel,
                    m.beskrivning AS moment_beskrivning,
                    m.arskurs_fran,
                    m.arskurs_till
                FROM moment m
                JOIN kunskapsomraden k ON k.id = m.omrade_id
                LEFT JOIN amnen a      ON a.id = k.amne_id
                WHERE m.arskurs_fran <= %s AND m.arskurs_till >= %s
            """
            params = [arskurs, arskurs]
            if amne_id:
                query += " AND k.amne_id = %s"
                params.append(amne_id)
            query += " ORDER BY k.namn, m.namn"
            cur.execute(query, params)
            return cur.fetchall() or []

def spara_ai_svar(
    inlamning_id: int,
    barn_id: int,
    moment_id: int,
    familj_id: int,
    handlaggare_id: int,
    kommentar: str,
    godkand: bool,
    stang_moment: bool,
    foljdfråga: str | None,
    konfidens: int,
    flaggad: bool = False,
    ai_status: str | None = None,
    **kwargs,
):
    # Använd status från AI-svaret om tillgänglig, annars mappa logiskt
    # ai_status skickas redan som parameter
    GILTIGA_STATUSAR = {
        "godkand", "delvis_godkand", "komplettering",
        "ej_relevant", "berom", "vidarebefordrad", "info", "ej_granskat"
    }
    
    if ai_status and ai_status in GILTIGA_STATUSAR:
        status = ai_status
    elif flaggad:
        status = "vidarebefordrad"
    elif godkand:
        status = "godkand"
    elif foljdfråga:
        status = "komplettering"
    else:
        status = "info"

    # Mappa till barn_moment_status (kvar | pagande | klar)
    bms_status = "klar" if (godkand and stang_moment) else "pagande"

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Spara kommentar
            cur.execute("""
                INSERT INTO handlaggare_kommentarer
                    (barn_id, moment_id, handlaggare_id, status, kommentar, skapad_at, uppdaterad_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (barn_id, moment_id, handlaggare_id, status, kommentar))

            # Spara följdfråga som separat rad
            if foljdfråga:
                cur.execute("""
                    INSERT INTO handlaggare_kommentarer
                        (barn_id, moment_id, handlaggare_id, status, kommentar, skapad_at, uppdaterad_at)
                    VALUES (%s, %s, %s, 'komplettering', %s, NOW(), NOW())
                """, (barn_id, moment_id, handlaggare_id, f"❓ Följdfråga: {foljdfråga}"))

            # Markera inlämning som granskad
            cur.execute("""
                UPDATE inlamningar
                SET ai_granskad    = true,
                    ai_flaggad     = %s,
                    ai_konfidens   = %s,
                    ai_godkand     = %s,
                    ai_granskad_at = NOW()
                WHERE id = %s
            """, (flaggad, konfidens, godkand, inlamning_id))

            # Uppdatera momentstatus
            cur.execute("""
                INSERT INTO barn_moment_status (barn_id, moment_id, status, uppdaterad_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (barn_id, moment_id)
                DO UPDATE SET status = EXCLUDED.status, uppdaterad_at = NOW()
            """, (barn_id, moment_id, bms_status))

        conn.commit()
        logger.info(f"✅ Sparat svar | godkänd={godkand} | status={status} | konfidens={konfidens}/5")

def setup_ai_kolumner():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE inlamningar
                ADD COLUMN IF NOT EXISTS ai_granskad    BOOLEAN DEFAULT false,
                ADD COLUMN IF NOT EXISTS ai_flaggad     BOOLEAN DEFAULT false,
                ADD COLUMN IF NOT EXISTS ai_godkand     BOOLEAN DEFAULT NULL,
                ADD COLUMN IF NOT EXISTS ai_konfidens   INTEGER DEFAULT NULL,
                ADD COLUMN IF NOT EXISTS ai_granskad_at TIMESTAMPTZ DEFAULT NULL
            """)
        conn.commit()
        logger.info("✅ AI-kolumner i inlamningar OK")
