"""
worker_enrich.py — ANALIZAR Y CALIFICAR (señal).

Toma perfiles con status='new' en lotes chicos, los visita una vez, y lee sus
datos del JSON que Instagram carga por detrás al abrir el perfil (la query
GraphQL "PolarisProfilePageContentQuery"). Es MUCHO más robusto que raspar el
DOM (las clases tipo x1i10hfl cambian; los modales se rompen).

De ese JSON (nodo data.user del perfil OBJETIVO, no del viewer) saca:
full_name, biography, category (etiqueta), follower_count, is_private y
bio_links (TODOS los enlaces, ya con la URL limpia).
El scoring usa name + bio + category; los links se revisan contra las ticketeras.

Correr:  python worker_enrich.py
Detener: Ctrl+C (lo ya guardado queda; el autocommit persiste cada perfil).
"""

import json
import re
import sys

from playwright.sync_api import sync_playwright

import db
import rate
import scoring
import session
from config import DELAY_PERFIL, TOPE_ENRICH, setup_logging

logger = setup_logging("enrich")

# Email en la bio.
RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Respaldos por si el JSON no llega: detectar "no existe" / "privado" en el DOM.
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


def _leer_perfil_json(page, username):
    """Navega al perfil e intercepta la respuesta GraphQL con sus datos.

    Al abrir un perfil, Instagram dispara 'PolarisProfilePageContentQuery' contra
    /api/graphql. La capturamos y devolvemos el nodo `data.user` del perfil
    OBJETIVO (verificando el username, para no confundirlo con el `viewer` =
    la cuenta logueada). Devuelve el dict `user`, o None si no llegó.
    """
    captura = {}

    def _on_response(response):
        if captura.get("user") or "/api/graphql" not in response.url:
            return
        try:
            body = json.loads(response.text())
        except Exception:
            return
        user = (body.get("data") or {}).get("user")
        if not isinstance(user, dict):
            return
        # Debe ser el perfil objetivo y traer datos de perfil (no una hovercard).
        if (user.get("username") or "").lower() != username.lower():
            return
        if "biography" not in user and "bio_links" not in user:
            return
        captura["user"] = user

    page.on("response", _on_response)
    try:
        page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
        rate.dormir((3.0, 6.0), logger, "carga perfil")
        rate.revisar_bloqueo(page, logger)
        # Espera a que llegue la query del perfil (hasta ~8s).
        for _ in range(16):
            if captura.get("user"):
                break
            page.wait_for_timeout(500)
    finally:
        page.remove_listener("response", _on_response)

    return captura.get("user")


def enriquecer_perfil(page, username):
    """Devuelve un dict {tipo, ...}. tipo: 'ok' | 'private' | 'unknown' | 'fallo'."""
    user = _leer_perfil_json(page, username)

    if not user:
        # No llegó el JSON: mira si el DOM dice "no existe" o "privado".
        try:
            cuerpo = page.inner_text("body").lower()
        except Exception:
            cuerpo = ""
        if any(s in cuerpo for s in SENALES_NO_EXISTE):
            return {"tipo": "unknown"}
        if any(s in cuerpo for s in SENALES_PRIVADO):
            return {"tipo": "private"}
        return {"tipo": "fallo"}  # no se pudo leer; se reintenta luego

    if user.get("is_private"):
        return {"tipo": "private"}

    # Todos los enlaces: bio_links trae la URL ya limpia; external_url de respaldo.
    links = []
    for bl in (user.get("bio_links") or []):
        u = bl.get("url") or bl.get("lynx_url")
        if u:
            links.append(u)
    if user.get("external_url"):
        links.append(user["external_url"])
    links = list(dict.fromkeys(links))  # sin duplicados, conserva orden

    bio = user.get("biography") or ""
    m = RE_EMAIL.search(bio)

    return {
        "tipo": "ok",
        "name": user.get("full_name"),
        "bio": bio or None,
        # La etiqueta viene como 'category' (esta query) o 'category_name' (otras).
        "categoria": user.get("category") or user.get("category_name"),
        "followers": user.get("follower_count"),
        "links": links,
        "email": m.group(0) if m else None,
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
                elif datos["tipo"] == "fallo":
                    db.marcar_fallido(conn, u)
                    logger.warning(f"@{u}: no se pudo leer el JSON (status=failed, se reintenta).")
                else:
                    texto = " ".join(filter(None, [
                        datos.get("name"), datos.get("bio"), datos.get("categoria"),
                    ]))
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
                    logger.info(
                        f"@{u}: score={score} verdict={verdict} sell_tickets={sell} "
                        f"followers={datos.get('followers')} cat='{datos.get('categoria')}' ({razon})"
                    )

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
