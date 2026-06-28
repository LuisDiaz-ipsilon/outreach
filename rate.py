"""
rate.py — Ritmo humano y detección de bloqueo (lógica delicada compartida).

Aquí vive todo lo que protege la cuenta:
  - dormir(): pausas aleatorias entre acciones (nada de ritmos de robot).
  - revisar_bloqueo(): si Instagram muestra un challenge / rate-limit, FRENA EN
    SECO lanzando CuentaBloqueada para que el worker pare y tú cambies de cuenta.

El tope de sesión (por cantidad) lo lleva cada worker con las constantes de config.
"""

import random
import time


class CuentaBloqueada(Exception):
    """Instagram mostró un bloqueo/challenge. Hay que detenerse y cambiar de cuenta."""


# Frases que Instagram muestra cuando limita o bloquea (inglés y español).
# Si ves otra en tus logs, agrégala aquí.
SENALES_BLOQUEO = [
    "try again later",
    "please wait a few minutes",
    "we restrict certain activity",
    "your account has been temporarily",
    "challenge_required",
    "intentalo de nuevo mas tarde",
    "intenta de nuevo mas tarde",
    "espera unos minutos",
    "restringimos cierta actividad",
    "tu cuenta ha sido suspendida",
]


def dormir(rango, logger=None, motivo: str = ""):
    """Duerme un tiempo aleatorio dentro de `rango` = (min, max) segundos."""
    segundos = random.uniform(rango[0], rango[1])
    if logger:
        texto = f"durmiendo {segundos:.1f}s" + (f" ({motivo})" if motivo else "")
        logger.info(texto)
    time.sleep(segundos)


def revisar_bloqueo(page, logger):
    """Inspecciona la página actual; si detecta señal de bloqueo, FRENA EN SECO.

    Lanza CuentaBloqueada (el worker la captura, reporta y termina).
    """
    try:
        cuerpo = page.inner_text("body").lower()
    except Exception:
        return  # si no se puede leer el body, no asumimos bloqueo

    for senal in SENALES_BLOQUEO:
        if senal in cuerpo:
            logger.error("=" * 60)
            logger.error("🛑 CUENTA BLOQUEADA — DETENTE Y CAMBIA DE CUENTA A MANO")
            logger.error(f"   señal detectada: '{senal}'")
            logger.error("=" * 60)
            raise CuentaBloqueada(senal)
