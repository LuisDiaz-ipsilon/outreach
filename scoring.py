"""
scoring.py — Pesos y lógica de calificación.

ESTE ES EL ÚNICO ARCHIVO QUE TUNEAS PARA EL SCORING. No tiene nada de scraping.

Cómo funciona:
  score = suma de los pesos de las keywords encontradas (en name + bio)
        + peso por cada link que apunte a una ticketera conocida,
        con TOPE en 100.
  Lead si score >= UMBRAL_LEAD.

Reglas acordadas:
  - Texto normalizado: minúsculas y sin acentos antes de comparar.
  - Coincidencia por PALABRA COMPLETA: "dj" NO suma dentro de "adjunto".
  - Un link de ticketera real activa sell_tickets=true.
  - Sin señales negativas: si no acumula puntos, simplemente no es lead.

>>> Llena/ajusta las dos tablas de abajo (PESOS_KEYWORDS y DOMINIOS_TICKETERA). <<<
"""

import re
import unicodedata

# ─────────────────────────────────────────────────────────────────────────────
# ⚙️  TUNEABLE — pesos por keyword (1 palabra cada una, en minúsculas sin acentos)
#    Agrega, quita o repesa libremente. El número es el peso.
#    Propuesta de arranque; AJÚSTALA a tu criterio.
# ─────────────────────────────────────────────────────────────────────────────
PESOS_KEYWORDS = {
    # Venta directa (señal fortísima)
    "boletos": 100, "boleto": 100, "ticket": 100, "tickets": 100,
    "entradas": 100, "entrada": 100, "comprar": 100, "compra": 100,
    "preventa": 100, "cover": 100,

    # Organizador / mundo de eventos
    "evento": 30, "eventos": 30, "festival": 30, "concierto": 30,
    "presenta": 30, "booking": 30, "promotor": 30, "productora": 30,
    "lineup": 30, "tour": 30, "tocada": 30, "rave": 30, "fiesta": 30,

    # Rol / lugar
    "dj": 10, "venue": 10, "club": 10, "antro": 10, "bar": 10,
    "salon": 10, "terraza": 10,

    # Género musical (contexto débil)
    "techno": 5, "house": 5, "rock": 5, "metal": 5,
    "reggaeton": 5, "cumbia": 5, "electronica": 5, "edm": 5, "trap": 5,
}

# ─────────────────────────────────────────────────────────────────────────────
# ⚙️  TUNEABLE — dominios de ticketeras conocidas.
#    Si CUALQUIER link del perfil contiene uno de estos, suma PESO_TICKETERA
#    y marca sell_tickets=true. Pon los dominios que uses en México.
#    (Solo el dominio basta: "passline" matchea "passline.com/eventos/...")
# ─────────────────────────────────────────────────────────────────────────────
DOMINIOS_TICKETERA = [
    # "eventbrite.com",
    # "passline.com",
    # "boletia.com",
    # "ticketmaster.com.mx",
    # "arema.mx",
    # "shotgun.live",
    # ... AGREGA AQUÍ ...
]

# ─────────────────────────────────────────────────────────────────────────────
# ⚙️  TUNEABLE — constantes
# ─────────────────────────────────────────────────────────────────────────────
PESO_TICKETERA = 100   # peso de un link de ticketera
UMBRAL_LEAD = 10       # score >= esto => verdict 'lead'
TOPE_SCORE = 100       # el score nunca pasa de aquí


def normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita acentos. '' si el texto es None/vacío."""
    if not texto:
        return ""
    t = texto.lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t


def calcular_score(texto: str, links):
    """Calcula el score de un perfil.

    `texto`  -> name + bio (se normaliza aquí dentro).
    `links`  -> lista de URLs externas del perfil (pueden ser varias).

    Devuelve una tupla: (score:int, score_reason:str, sell_tickets:bool).
    """
    t = normalizar(texto)
    score = 0
    razones = []

    # Keywords por palabra completa
    for palabra, peso in PESOS_KEYWORDS.items():
        if re.search(rf"\b{re.escape(palabra)}\b", t):
            score += peso
            razones.append(palabra)

    # Links de ticketera (revisa TODOS los links del perfil)
    sell_tickets = False
    for link in (links or []):
        l = normalizar(link)
        for dom in DOMINIOS_TICKETERA:
            if dom and dom in l:
                score += PESO_TICKETERA
                sell_tickets = True
                if dom not in razones:
                    razones.append(dom)
                break  # un link cuenta una sola vez

    score = min(score, TOPE_SCORE)
    score_reason = "+".join(dict.fromkeys(razones))  # sin duplicados, en orden
    return score, score_reason, sell_tickets


def clasificar(score: int) -> str:
    """Verdict según el score. (private/unknown los pone el worker.)"""
    return "lead" if score >= UMBRAL_LEAD else "discarded_attendee"


if __name__ == "__main__":
    # Demo local (no toca Instagram ni la DB): muestra cómo puntúa un texto.
    ejemplo_texto = "DJ y productor | Techno | Compra tus boletos aqui"
    ejemplo_links = ["https://passline.com/eventos/mi-fiesta"]
    s, r, st = calcular_score(ejemplo_texto, ejemplo_links)
    print(f"texto:   {ejemplo_texto}")
    print(f"links:   {ejemplo_links}")
    print(f"score={s}  verdict={clasificar(s)}  sell_tickets={st}  razon='{r}'")
