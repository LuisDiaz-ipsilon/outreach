"""
config.py — Configuración central de Outreach.

Reúne todos los valores OPERATIVOS del sistema: conexión a la base de datos,
ritmo humano (delays), topes de sesión, logging y conexión a Chrome.

Las credenciales de la DB se leen de .env (fuera de git). El resto son
parámetros que puedes tunear a mano sin tocar la lógica de los workers.

(Los pesos y keywords del scoring NO viven aquí: están en scoring.py.)
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Raíz del proyecto y carga del .env
RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")


# ─────────────────────────────────────────────────────────────────────────────
# Base de datos (PostgreSQL en la Raspberry Pi)
# Credenciales desde .env — NUNCA se versionan.
# ─────────────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.22"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "outreachdb"),
    "user": os.getenv("DB_USER", "outreach"),
    "password": os.getenv("DB_PASSWORD", ""),
}


# ─────────────────────────────────────────────────────────────────────────────
# Ritmo humano (lo usa rate.py). Delays en SEGUNDOS, como rango (min, max):
# el sistema elige un valor aleatorio dentro del rango para no ser predecible.
# Súbelos si quieres ir más lento/seguro; bájalos bajo tu propio riesgo.
# ─────────────────────────────────────────────────────────────────────────────
DELAY_SCROLL = (3.0, 8.0)    # entre tandas de scroll en la lista de following
DELAY_PERFIL = (15.0, 40.0)  # entre perfiles en worker_enrich (lo más caro/riesgoso)
DELAY_SEED = (30.0, 90.0)    # entre seeds en worker_following


# ─────────────────────────────────────────────────────────────────────────────
# Topes de sesión — por CANTIDAD, no por tiempo. Al alcanzarlos, el worker
# corta limpio y reporta cuántos procesó.
# ─────────────────────────────────────────────────────────────────────────────
TOPE_FOLLOWING = 500   # usernames nuevos por corrida de worker_following
TOPE_ENRICH = 100      # perfiles por corrida de worker_enrich


# ─────────────────────────────────────────────────────────────────────────────
# Chrome (logueado a mano, con puerto de debug remoto).
# En Windows 10 abre Chrome así, UNA vez, antes de correr los workers:
#
#   "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
#       --remote-debugging-port=9222 --user-data-dir="C:\\outreach-chrome"
#
# El --user-data-dir crea un perfil aparte (no el personal), ideal para
# cuentas quemables.
# ─────────────────────────────────────────────────────────────────────────────
CHROME_CDP = os.getenv("CHROME_CDP", "http://localhost:9222")


# ─────────────────────────────────────────────────────────────────────────────
# Logging — sale a consola Y a un archivo único (modo append). El dueño trunca
# ese archivo a mano cuando crezca; el programa no lo rota.
# Formato de cada línea:  2026-06-28 14:32:07 | following | mensaje
# ─────────────────────────────────────────────────────────────────────────────
LOG_FILE = RAIZ / "outreach.log"


def setup_logging(nombre: str) -> logging.Logger:
    """Devuelve un logger configurado con salida dual (consola + archivo).

    `nombre` aparece en cada línea (ej. "following", "enrich"), útil para
    distinguir qué worker la escribió en el log compartido.
    """
    logger = logging.getLogger(nombre)
    if logger.handlers:  # no dupliques handlers si se llama dos veces
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    consola = logging.StreamHandler()
    consola.setFormatter(fmt)
    logger.addHandler(consola)

    archivo = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    archivo.setFormatter(fmt)
    logger.addHandler(archivo)

    return logger
