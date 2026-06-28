"""
worker_enrich.py — ANALIZAR Y CALIFICAR (señal).

Toma perfiles con status='new' en lotes chicos, los visita una vez, extrae
name/bio/followers/links/email, corre el scoring y guarda el verdict.
Es el worker más caro y riesgoso (una carga de página por perfil).

Correr:  python worker_enrich.py
Detener: Ctrl+C (lo ya guardado queda; el autocommit persiste cada perfil).

⚠️  La extracción depende del DOM de Instagram, que cambia seguido. Las
    funciones marcadas con TODO casi seguro necesitarán ajuste fino la primera
    vez que corras en vivo con un perfil real. Es normal en scraping de IG.
"""

import re
import sys
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import sync_playwright

import db
import rate
import scoring
import session
from config import DELAY_PERFIL, TOPE_ENRICH, setup_logging

logger = setup_logging("enrich")

# Patrón de email para buscar en la bio.
RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Frases de "perfil no existe" y "perfil privado" (inglés y español).
SENALES_NO_EXISTE = [
    "sorry, this page isn't available",
    "esta página no está disponible",
    "la página no está disponible",
]
SENALES_PRIVADO = [
    "this account is private",
    "esta cuenta es privada",
    "cuenta privada",
]


def _texto_seguro(page, selector):
    """inner_text del primer elemento que matchee, o None si no hay/error."""
    try:
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else None
    except Exception:
        return None


def _extraer_name(page):
    """Nombre visible del perfil.  TODO: verificar selector en vivo."""
    # og:title suele venir como "Name (@username) • Instagram photos..."
    try:
        title = page.get_attribute('meta[property="og:title"]', "content")
        if title:
            return title.split("(@")[0].strip(" •")
    except Exception:
        pass
    return _texto_seguro(page, "header h1, header h2")


def _extraer_bio(page):
    """Texto de la bio.  TODO: verificar selector en vivo (es lo más frágil)."""
    # Intento por estructura del header; si falla, queda en None y no pasa nada.
    bio = _texto_seguro(page, "header section > div:last-child > span")
    if bio:
        return bio
    return _texto_seguro(page, 'header section span[dir="auto"]')


def _extraer_followers(page):
    """Número de seguidores desde og:description.  Aproximado pero estable."""
    try:
        desc = page.get_attribute('meta[property="og:description"]', "content")
    except Exception:
        desc = None
    if not desc:
        return None
    # Formato: "1,234 Followers, 567 Following, 89 Posts ..." (o en español)
    m = re.search(r"([\d.,]+)\s+(followers|seguidores)", desc.lower())
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", "").replace(".", ""))
    except ValueError:
        return None


def _extraer_links(page):
    """Todos los links externos del perfil (pueden ser varios).

    Instagram envuelve los externos en 'l.instagram.com/?u=<url>'; los
    desenvuelve. TODO: verificar selector en vivo.
    """
    try:
        hrefs = page.eval_on_selector_all("header a[href]", "els => els.map(e => e.href)")
    except Exception:
        return []

    links = []
    for h in hrefs:
        if not h:
            continue
        if "l.instagram.com" in h:
            q = parse_qs(urlparse(h).query)
            if "u" in q:
                links.append(unquote(q["u"][0]))
        elif h.startswith("http") and "instagram.com" not in h:
            links.append(h)
    return list(dict.fromkeys(links))  # sin duplicados, conserva orden


def enriquecer_perfil(page, username):
    """Carga el perfil y devuelve un dict con tipo y datos.

    tipo: 'ok' (con datos), 'private', 'unknown'.
    """
    page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
    rate.dormir((3.0, 6.0), logger, "carga perfil")
    rate.revisar_bloqueo(page, logger)

    try:
        cuerpo = page.inner_text("body").lower()
    except Exception:
        cuerpo = ""

    if any(s in cuerpo for s in SENALES_NO_EXISTE):
        return {"tipo": "unknown"}
    if any(s in cuerpo for s in SENALES_PRIVADO):
        return {"tipo": "private"}

    bio = _extraer_bio(page)
    email_match = RE_EMAIL.search(bio or "")
    return {
        "tipo": "ok",
        "name": _extraer_name(page),
        "bio": bio,
        "followers": _extraer_followers(page),
        "links": _extraer_links(page),
        "email": email_match.group(0) if email_match else None,
    }


def main():
    logger.info("=" * 60)
    logger.info("worker_enrich: INICIO")
    procesados = 0
    with sync_playwright() as p:
        browser, context, page = session.conectar(p, logger)
        if not session.verificar_login(page, logger):
            sys.exit(1)

        conn = db.get_connection()
        try:
            lote = db.get_lote_nuevos(conn, TOPE_ENRICH)
            logger.info(f"{len(lote)} perfil(es) 'new' en este lote (tope {TOPE_ENRICH}).")

            for row in lote:
                u = row["username"]
                logger.info(f"--- @{u} ---")
                datos = enriquecer_perfil(page, u)

                if datos["tipo"] == "private":
                    db.marcar_verdict(conn, u, "private")
                    logger.info(f"@{u}: privado (registrado, no se re-visita).")
                elif datos["tipo"] == "unknown":
                    db.marcar_verdict(conn, u, "unknown")
                    logger.info(f"@{u}: no disponible / no existe.")
                else:
                    texto = f"{datos.get('name') or ''} {datos.get('bio') or ''}"
                    score, razon, sell = scoring.calcular_score(texto, datos.get("links"))
                    verdict = scoring.clasificar(score)
                    external = "\n".join(datos.get("links") or []) or None
                    db.guardar_enrich(
                        conn, u,
                        name=datos.get("name"), bio=datos.get("bio"),
                        email=datos.get("email"), external_link=external,
                        followers=datos.get("followers"), sell_tickets=sell,
                        score=score, score_reason=razon or None, verdict=verdict,
                    )
                    logger.info(f"@{u}: score={score} verdict={verdict} sell_tickets={sell} ({razon})")

                procesados += 1
                rate.dormir(DELAY_PERFIL, logger, "entre perfiles")
                rate.revisar_bloqueo(page, logger)

        except rate.CuentaBloqueada:
            logger.error("DETENIDO por bloqueo de cuenta. Cambia de cuenta y vuelve a lanzar.")
        except KeyboardInterrupt:
            logger.info("interrumpido por el usuario (Ctrl+C).")
        finally:
            logger.info(f"worker_enrich: FIN — {procesados} perfil(es) procesados esta sesión.")
            logger.info(f"status de counts: {db.resumen_status(conn)}")
            conn.close()
            logger.info("=" * 60)


if __name__ == "__main__":
    main()
