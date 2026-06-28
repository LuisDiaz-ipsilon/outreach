"""
session.py — Engancharse a Chrome y verificar la sesión de Instagram.

NO automatiza el login (eso quema cuentas). Tú abres Chrome a mano, logueado,
con el puerto de debug; este módulo se conecta a esa sesión vía CDP.

Abrir Chrome (Windows 10), UNA vez antes de correr los workers:
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
      --remote-debugging-port=9222 --user-data-dir="C:\\outreach-chrome"
"""

import time

from config import CHROME_CDP


def conectar(playwright, logger=None):
    """Se engancha al Chrome ya abierto (puerto de debug) vía CDP.

    Devuelve (browser, context, page) reutilizando la sesión existente.
    Lanza RuntimeError si no encuentra el navegador/contexto.
    """
    if logger:
        logger.info(f"conectando a Chrome en {CHROME_CDP} ...")
    browser = playwright.chromium.connect_over_cdp(CHROME_CDP)

    if not browser.contexts:
        raise RuntimeError(
            "Chrome no tiene ningún contexto abierto. ¿Lo abriste con "
            "--remote-debugging-port y al menos una pestaña?"
        )

    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    _aplicar_stealth(page)
    if logger:
        logger.info("conectado a la sesión de Chrome.")
    return browser, context, page


def verificar_login(page, logger) -> bool:
    """Confirma que el Chrome enganchado tenga sesión de Instagram activa.

    Si redirige a la pantalla de login, devuelve False (el worker debe abortar
    sin golpear Instagram).
    """
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    time.sleep(2)

    if "/accounts/login" in page.url:
        logger.error("NO hay sesión de Instagram (redirige a login).")
        logger.error("Abre Instagram logueado en el Chrome del puerto de debug y reintenta.")
        return False

    logger.info("sesión de Instagram detectada — OK.")
    return True


def _aplicar_stealth(page):
    """Aplica playwright-stealth si está instalado. Es OPCIONAL: como nos
    enganchamos a un Chrome real, su ausencia no rompe nada (ver README)."""
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
    except Exception:
        pass
