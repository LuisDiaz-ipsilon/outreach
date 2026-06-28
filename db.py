"""
db.py — Acceso a la base de datos (PostgreSQL en la Raspberry Pi).

SIN ORM: puro SQL crudo y SIEMPRE parametrizado (placeholders %s, nunca
concatenando strings) vía psycopg3. Todas las queries del sistema viven aquí;
los workers solo llaman a estas funciones.

La conexión va en AUTOCOMMIT: cada escritura persiste de inmediato. Así, si
Instagram bloquea la cuenta a media corrida, lo ya guardado queda a salvo.
"""

import psycopg
from psycopg.rows import dict_row

from config import DB_CONFIG


def get_connection():
    """Abre una conexión nueva a la DB (autocommit, filas como dict)."""
    return psycopg.connect(**DB_CONFIG, autocommit=True, row_factory=dict_row)


def test_connection() -> bool:
    """Prueba rápida: conecta, cuenta filas de cada tabla y reporta."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM counts")
            n_counts = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM seeds")
            n_seeds = cur.fetchone()["n"]
        print(f"OK - conexion exitosa. counts={n_counts} filas, seeds={n_seeds} filas")
        return True
    except Exception as e:
        print(f"ERROR de conexion: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SEEDS — los usa worker_following
# ─────────────────────────────────────────────────────────────────────────────

def get_seeds_activos(conn):
    """Seeds con actived=true y aún no completados.

    Orden: los menos recientemente tocados primero (para repartir el trabajo).
    Devuelve una lista de dicts.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT username, name, completed, last_scan
                 FROM seeds
                WHERE actived = true AND completed = false
                ORDER BY last_scan ASC NULLS FIRST"""
        )
        return cur.fetchall()


def marcar_seed_completado(conn, username: str):
    """Marca un seed como escaneado por completo (su círculo ya se recorrió)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE seeds SET completed = true, last_scan = now() WHERE username = %s",
            (username,),
        )


def tocar_seed(conn, username: str):
    """Actualiza last_scan sin marcar completado (al pausar a media lista)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE seeds SET last_scan = now() WHERE username = %s",
            (username,),
        )


# ─────────────────────────────────────────────────────────────────────────────
# COUNTS — descubrimiento (worker_following)
# ─────────────────────────────────────────────────────────────────────────────

def insertar_username(conn, username: str, seed_origen: str) -> int:
    """Inserta un username nuevo (status='new' por default en la tabla).

    Dedup vía ON CONFLICT (username). Devuelve 1 si era nuevo, 0 si ya existía.
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO counts (username, seed_origen)
                    VALUES (%s, %s)
               ON CONFLICT (username) DO NOTHING""",
            (username, seed_origen),
        )
        return cur.rowcount


# ─────────────────────────────────────────────────────────────────────────────
# COUNTS — calificación (worker_enrich)
# ─────────────────────────────────────────────────────────────────────────────

def get_lote_nuevos(conn, limite: int):
    """Devuelve hasta `limite` perfiles con status='new'. Lista de dicts."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT username, seed_origen
                 FROM counts
                WHERE status = 'new'
                ORDER BY created_at ASC
                LIMIT %s""",
            (limite,),
        )
        return cur.fetchall()


def guardar_enrich(conn, username: str, *, name, bio, email, external_link,
                   followers, sell_tickets, score, score_reason, verdict):
    """Guarda el resultado del enriquecimiento de un perfil público.

    Deja status='scanned'. Se llama con argumentos por nombre para no
    confundir el orden de tantos campos.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE counts SET
                       name = %s, bio = %s, email = %s, external_link = %s,
                       followers = %s, sell_tickets = %s, score = %s,
                       score_reason = %s, verdict = %s, status = 'scanned'
                 WHERE username = %s""",
            (name, bio, email, external_link, followers, sell_tickets,
             score, score_reason, verdict, username),
        )


def marcar_verdict(conn, username: str, verdict: str):
    """Marca un perfil como 'scanned' con un verdict simple, sin scoring.

    Para perfiles privados ('private') o que no existen ('unknown'): ya se
    procesaron, no se vuelven a visitar, pero la fila se conserva.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE counts SET status = 'scanned', verdict = %s WHERE username = %s",
            (verdict, username),
        )


def marcar_fallido(conn, username: str):
    """Marca un perfil como 'failed' (error técnico; se puede reintentar)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE counts SET status = 'failed' WHERE username = %s",
            (username,),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Reportes
# ─────────────────────────────────────────────────────────────────────────────

def resumen_status(conn) -> dict:
    """Cuenta filas de counts agrupadas por status. Dict {status: n}."""
    with conn.cursor() as cur:
        cur.execute("SELECT status, count(*) AS n FROM counts GROUP BY status")
        return {row["status"]: row["n"] for row in cur.fetchall()}


if __name__ == "__main__":
    # Permite probar la conexión con:  python db.py
    test_connection()
