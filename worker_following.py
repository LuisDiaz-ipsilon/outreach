"""
worker_following.py — DESCUBRIR (volumen).

Por cada seed activo: abre su lista de "following", hace scroll en tandas y
guarda los usernames nuevos en `counts` (status='new'). No lee bios ni puntúa.

Correr:  python worker_following.py
Detener: Ctrl+C (retoma por seed; el dedup hace que repetir sea inofensivo).

⚠️  Los selectores del DOM de Instagram cambian seguido. Si deja de descubrir,
    revisa las funciones marcadas con TODO con un perfil real abierto.
"""

import re
import sys

from playwright.sync_api import sync_playwright

import db
import rate
import session
from config import DELAY_SCROLL, DELAY_SEED, TOPE_FOLLOWING, setup_logging

logger = setup_logging("following")

# Rutas que NO son perfiles (para descartarlas al recolectar hrefs).
NO_PERFILES = {
    "explore", "reels", "direct", "accounts", "p", "stories",
    "about", "privacy", "terms", "settings",
}


def _username_de_href(href):
    """Convierte '/usuario/' en 'usuario'. Devuelve None si no es un perfil."""
    if not href:
        return None
    h = href.strip("/")
    if not h or "/" in h:        # rutas con barras internas no son perfiles
        return None
    if h in NO_PERFILES:
        return None
    return h


def descubrir_following(page, seed, conn):
    """Recorre la lista de following de un seed y guarda usernames nuevos.

    Devuelve (nuevos:int, completado:bool).
    `completado` = True si se agotó la lista; False si cortó por el tope.
    """
    nuevos = 0
    page.goto(f"https://www.instagram.com/{seed}/", wait_until="domcontentloaded")
    rate.dormir((2.0, 4.0), logger, "carga perfil")
    rate.revisar_bloqueo(page, logger)

    # Abrir el modal de "seguidos" (following). El link ya NO usa /following/;
    # ahora es un <a href="#"> cuyo texto termina en "seguidos" (o "following"
    # si la cuenta está en inglés). Clickeamos por TEXTO, no por href.
    try:
        page.get_by_role(
            "link", name=re.compile(r"\bseguidos\b|\bfollowing\b", re.I)
        ).first.click(timeout=10000)
    except Exception:
        try:
            page.click('a:has-text("seguidos")', timeout=5000)  # respaldo
        except Exception:
            logger.warning(f"@{seed}: no pude abrir 'seguidos' (¿selector cambió o perfil privado?). Salto.")
            return nuevos, True

    rate.dormir((2.0, 4.0), logger, "abre modal")

    vistos = set()
    tandas_sin_nuevos = 0
    while tandas_sin_nuevos < 5:          # 5 tandas seguidas sin nada => fin
        # Recolecta los usernames visibles dentro del diálogo.
        # TODO: verificar selector del diálogo en vivo.
        try:
            hrefs = page.eval_on_selector_all(
                'div[role="dialog"] a[href^="/"]',
                "els => els.map(e => e.getAttribute('href'))",
            )
        except Exception:
            logger.warning(f"@{seed}: no pude leer la lista del modal. Salto seed.")
            return nuevos, True

        en_tanda = 0
        for h in hrefs:
            u = _username_de_href(h)
            if not u or u in vistos or u == seed:
                continue
            vistos.add(u)
            if db.insertar_username(conn, u, seed):   # 1 si era nuevo
                nuevos += 1
                en_tanda += 1
                if nuevos >= TOPE_FOLLOWING:
                    logger.info(f"@{seed}: tope de sesión alcanzado ({TOPE_FOLLOWING}).")
                    return nuevos, False

        logger.info(f"@{seed}: +{en_tanda} nuevos esta tanda (seed: {nuevos}, vistos: {len(vistos)})")
        tandas_sin_nuevos = tandas_sin_nuevos + 1 if en_tanda == 0 else 0

        # Scroll: lleva el último elemento a la vista para forzar la carga de más.
        # TODO: verificar que esto cargue más en vivo.
        try:
            page.eval_on_selector_all(
                'div[role="dialog"] a[href^="/"]',
                "els => { if (els.length) els[els.length - 1].scrollIntoView(); }",
            )
        except Exception:
            pass

        rate.dormir(DELAY_SCROLL, logger, "scroll following")
        rate.revisar_bloqueo(page, logger)

    return nuevos, True


def main():
    logger.info("=" * 60)
    logger.info("worker_following: INICIO")
    total = 0
    with sync_playwright() as p:
        browser, context, page = session.conectar(p, logger)
        if not session.verificar_login(page, logger):
            sys.exit(1)

        conn = db.get_connection()
        try:
            seeds = db.get_seeds_activos(conn)
            logger.info(f"{len(seeds)} seed(s) activo(s) por procesar.")

            for s in seeds:
                if total >= TOPE_FOLLOWING:
                    logger.info("tope de sesión global alcanzado; corto limpio.")
                    break

                seed = s["username"]
                logger.info(f"--- seed @{seed} ---")
                nuevos, completado = descubrir_following(page, seed, conn)
                total += nuevos

                if completado:
                    db.marcar_seed_completado(conn, seed)
                    logger.info(f"@{seed}: completado (+{nuevos} nuevos).")
                else:
                    db.tocar_seed(conn, seed)   # cortado por tope: solo actualiza last_scan
                    logger.info(f"@{seed}: pausado por tope (+{nuevos} nuevos).")

                rate.dormir(DELAY_SEED, logger, "entre seeds")

        except rate.CuentaBloqueada:
            logger.error("DETENIDO por bloqueo de cuenta. Cambia de cuenta y vuelve a lanzar.")
        except KeyboardInterrupt:
            logger.info("interrumpido por el usuario (Ctrl+C).")
        finally:
            logger.info(f"worker_following: FIN — {total} usernames nuevos esta sesión.")
            logger.info(f"status de counts: {db.resumen_status(conn)}")
            conn.close()
            logger.info("=" * 60)


if __name__ == "__main__":
    main()
