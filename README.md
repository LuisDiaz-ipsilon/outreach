# Outreach — Motor de descubrimiento de leads para PAS Ticket

Sistema de **inteligencia comercial** para encontrar organizadores de eventos y músicos en Instagram, calificarlos, y dejarlos listos para un outreach **manual** (copiar/pegar desde la base de datos).

No es un "Instagram scraper" genérico ni un bot de mensajería. Es un motor que construye una base de datos propia de potenciales clientes para PAS Ticket.

---

## Objetivo

Pasar de:

```
15 perfiles que ya conozco  →  miles descubiertos  →  los X que de verdad venden eventos
```

El resultado consumible es una consulta:

```sql
SELECT * FROM counts WHERE verdict = 'lead' AND score >= 10;
```

De ahí el usuario arma su CSV a mano y hace el contacto desde su cuenta oficial.

### Quién es un lead
DJs, dueños de bandas, promotores, dueños de antros/venues, organizadores de expos, productoras, festivales, y en general cualquier perfil que **cobre entrada** o **venda boletos**.

---

## Principios de diseño (qué SÍ y qué NO)

**SÍ:**
- Solo lectura de datos **públicos**.
- Outreach 100% manual (el sistema redacta, el humano copia/pega/envía).
- Cuentas quemables (chips baratos), nunca la cuenta personal o de negocio.
- Login manual en Chrome; el sistema se engancha a una sesión ya abierta.
- Control de ritmo (delays humanos, lotes chicos) como parte del núcleo, no como parche.
- Monitoreo presencial: si una cuenta se bloquea, el humano la cambia a mano.
- El internet se usaran paquetes de datos ilimatados de telcel del chip desechable

**NO:**
- No DMs automáticos por Instagram.
- No se guardan credenciales de Instagram en la base de datos.
- No n8n, no Google Sheets, no Gmail.
- No correr un solo proceso gigante.
- No buscar un proyecto de GitHub que lo haga "todo".

---

## Arquitectura

Dos workers que se coordinan **a través de la base de datos** (sin colas ni mensajería), vía el campo `status`:

```
seeds ──▶ worker_following ──▶ counts (status='new')
                                   │
                                   ▼
                          worker_enrich ──▶ counts (status='scanned' + score + verdict)
                                   │
                                   ▼
                       consulta SQL ──▶ CSV (manual)
```

`worker_following` **produce** (volumen). `worker_enrich` **consume** (señal). Separar volumen (rápido, barato) de análisis (lento, caro, riesgoso) significa que si Instagram bloquea en la fase cara, lo ya descubierto queda a salvo.

> Con **una sola cuenta**, los workers corren **secuencial**, nunca en paralelo (dos navegadores con la misma sesión = bandera roja).

---

## Los dos workers

### `worker_following` — descubrir
- **Función:** encontrar usernames nuevos.
- **Entrada:** `seeds` con `actived = true`.
- **Proceso:** por cada seed, abre su lista de *following*, hace scroll en tandas, guarda usernames nuevos.
- **Salida:** filas en `counts` con `status='new'`, `seed_origen`.
- **Aporta:** **volumen.** Convierte ~15 seeds en miles de candidatos.
- No lee bios, no puntúa, no clasifica.

### `worker_enrich` — analizar y calificar
- **Función:** tomar los `new`, visitarlos, leer, puntuar y dar veredicto.
- **Entrada:** `counts WHERE status='new'` (lotes chicos).
- **Proceso:** abre cada perfil, extrae nombre/bio/link/followers, normaliza el texto (minúsculas, sin acentos), corre el scoring.
- **Salida:** misma fila con `status='scanned'`, `score`, `score_reason`, `verdict`.
- **Aporta:** **señal.** Convierte la lista cruda en clientes reales filtrados.
- Es el worker más riesgoso: una carga de página por perfil → va más lento y en lotes más chicos.

### Comportamiento compartido
- **Dedup:** `UNIQUE(username)` + `ON CONFLICT DO NOTHING`. Re-ver un username no rompe ni duplica.
- **Tope de sesión:** por **cantidad** (ej. N usernames / N perfiles). Al llegar, corta limpio y reporta.
- **Detección de bloqueo:** si Instagram muestra challenge o "Try again later", **frena en seco**, no insiste, y avisa fuerte para cambiar de cuenta.
- **Privados:** se descartan del análisis pero se **registran** (`verdict='private'`) para no re-visitarlos en el futuro.

---

## Esquema de base de datos (PostgreSQL)

### `counts`
| columna | tipo | nota |
|---|---|---|
| username | text UNIQUE NOT NULL | identidad |
| name | text NULL | |
| bio | text NULL | descripción del perfil |
| email | text NULL | si aparece en bio |
| external_link | text NULL | link de bio (passline, linktree, etc.) |
| followers | int NULL | |
| sell_tickets | bool DEFAULT false | true solo si hay link de ticketera conocida |
| profile_type | text NULL | libre: "dj", "organizador", "dj, organizador" |
| music_genre | text NULL | libre: "techno", "rock", null |
| score | int DEFAULT 0 | umbral de lead: 10 / 100 |
| score_reason | text NULL | qué señales sumaron: "boletos+passline+dj" |
| status | text DEFAULT 'new' | pipeline: `new` → `scanned` → `failed` |
| verdict | text NULL | clasificación: `lead`, `discarded_attendee`, `private`, `unknown` |
| message | text NULL | mensaje IA para copiar/pegar (fase posterior) |
| seed_origen | text NULL | de qué seed salió |
| created_at | timestamptz DEFAULT now() | |
| updated_at | timestamptz DEFAULT now() | |

> **Clave del diseño:** `status` (¿ya lo procesé?) y `verdict` (¿qué es?) son columnas **separadas**. Así un privado es `status='scanned'` + `verdict='private'` sin perder el rastro de que ya se revisó.

### `seeds`
| columna | tipo | nota |
|---|---|---|
| username | text UNIQUE NOT NULL | |
| name | text NULL | |
| completed | bool DEFAULT false | true cuando se escaneó todo su círculo |
| actived | bool DEFAULT true | lo controla el humano; false = no se usa |
| last_scan | timestamptz NULL | para resume / saber cuándo se tocó |

---

## Scoring

Vive en un solo archivo (`scoring.py`) para tunear fácil. Los **pesos los define el dueño del proyecto**.

- **Umbral de lead:** `score >= 10` (de 100).
- **Señales en bio** (keywords normalizadas): `comprar`, `comprar tickets`, `tickets`, `entradas`, `boletos`, `evento`, `dj`, `booking`, `festival`, etc.
- **Señales en link** (dominios de ticketeras): `passline`, `shotgun`, `eventbrite`, `boletia`, `ticketmaster`, `linktr.ee`.
- `sell_tickets = true` cuando se detecta un link de ticketera conocida.
- Siempre se guarda `score_reason` (qué disparó el puntaje), no solo el número.

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python |
| Automatización de navegador | Playwright + playwright-stealth |
| Navegador | Chrome (logueado a mano, con puerto de debug remoto) |
| Base de datos | PostgreSQL (en Raspberry Pi, red local) |
| Sesión | `storage_state.json` / conexión a Chrome ya abierto |
| Exportación | consulta SQL → CSV manual |
| IA (fase posterior) | redacción de mensajes personalizados |

**Entorno de ejecución:** máquina del usuario (Windows / Mac de desarrollo), Chrome abierto y logueado, conectado por red local a PostgreSQL en la Raspberry.

---

## Estructura del proyecto

```
outreach/
  config.py            # delays, tamaños de lote, keywords, rutas
  .env                 # credenciales de Postgres (fuera de git)
  schema.sql           # las 2 tablas
  db.py                # conexión + helpers
  session.py           # se engancha a Chrome / carga sesión, lanza stealth
  rate.py              # delays humanos, topes por sesión, detección de bloqueo
  scoring.py           # pesos de keywords/links → score + razón
  worker_following.py  # descubrir
  worker_enrich.py     # analizar y calificar
  storage_state.json   # (generado, fuera de git)
```

`rate.py` y `session.py` son compartidos: toda la lógica delicada (ritmo, bloqueos, sesión) vive en un solo lado, y los workers quedan delgados.

---

## Uso

```bash
# 1. (una vez) crear las tablas
psql -f schema.sql

# 2. abrir Chrome logueado en Instagram con puerto de debug
#    (comando exacto pendiente de definir)

# 3. descubrir
python worker_following.py

# 4. analizar y calificar
python worker_enrich.py

# detener cualquiera con Ctrl+C — retoma por el cursor de seed
```

---

## Alcance por fases

**v1 (actual):**
- [ ] `worker_following` (descubrimiento por *following* de seeds)
- [ ] `worker_enrich` (scoring por keywords de tickets/compra + links de ticketeras)
- Una sola cuenta, sin proxies, secuencial.

**Más adelante (no construir aún):**
- Pool de cuentas + rotación + cooldowns automáticos.
- Proxies residenciales/móviles.
- Otras estrategias de descubrimiento: hashtags, palabras clave en bio, comentarios, colaboraciones.
- Detección de flyers por OCR/visión.
- Generación de mensajes con IA.
- Otras fuentes: Facebook Events, Resident Advisor, Eventbrite, etc.

---

## Riesgos y notas honestas

- **Viola los ToS de Instagram** (scraping). El riesgo legal es bajo por ser datos públicos + read-only + outreach manual, pero existe.
- **Las cuentas se queman**, no las IPs residenciales (que solo reciben rate-limit temporal). Por eso los chips quemables.
- **Un VPS empeora el problema:** Instagram marca IPs de datacenter como sospechosas. Correr desde IP residencial (casa) es más seguro que un VPS pelón.
- **El cuello de botella real no es el código, es la gestión de cuentas:** calentar cuentas nuevas (warm-up de varios días) y rotarlas consume más tiempo que escribir scrapers.
- **El "resume" es a nivel seed completa**, no a media lista de following (el DOM no da cursor real). Para seeds con <2-3k following es perfecto; para mega-seeds es imperfecto y se resuelve después.