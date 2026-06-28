# Arquitectura y flujos — Outreach

Índice:
1. [Pipeline general](#1-pipeline-general)
2. [Flujo de `worker_following` (descubrir)](#2-flujo-de-worker_following-descubrir)
3. [Flujo de `worker_enrich` (calificar)](#3-flujo-de-worker_enrich-calificar)
4. [Estados de una fila en `counts`](#4-estados-de-una-fila-en-counts)
5. [Dependencias entre módulos](#5-dependencias-entre-módulos)

---

## 1. Pipeline general

Dos workers que se coordinan **a través de la base de datos** (sin colas), vía el
campo `status`. `worker_following` produce volumen; `worker_enrich` produce señal.
Con una sola cuenta corren **secuencial**, nunca en paralelo.

```mermaid
flowchart TD
    seeds[("tabla seeds<br/>(perfiles ancla)")]
    counts[("tabla counts<br/>(perfiles descubiertos)")]

    seeds --> wf["worker_following<br/>DESCUBRIR · volumen"]
    wf -->|"usernames nuevos · status=new"| counts
    counts -->|"lee status=new"| we["worker_enrich<br/>CALIFICAR · señal"]
    we -->|"score + verdict · status=scanned"| counts
    counts -->|"verdict=lead AND score>=10"| query["Consulta SQL"]
    query --> csv["CSV armado a mano"]
    csv --> outreach["Outreach MANUAL<br/>(copiar/pegar)"]
```

---

## 2. Flujo de `worker_following` (descubrir)

Por cada seed activo: abre su lista de *following*, hace scroll en tandas y
guarda usernames nuevos. No lee bios ni puntúa. El **dedup** (`ON CONFLICT`) hace
que repetir sea inofensivo.

```mermaid
flowchart TD
    inicio(["python worker_following.py"]) --> conecta["engancharse a Chrome (CDP)"]
    conecta --> login{"¿sesión de IG activa?"}
    login -->|no| abort(["abortar · avisar"])
    login -->|sí| getseeds["obtener seeds activos<br/>(actived=true, completed=false)"]
    getseeds --> loop{"¿quedan seeds y<br/>no se alcanzó el tope?"}
    loop -->|no| fin(["reportar total · terminar"])
    loop -->|sí| perfil["abrir perfil del seed"]
    perfil --> modal["abrir modal de following"]
    modal --> scroll["scroll en tanda<br/>extraer usernames visibles"]
    scroll --> insert["INSERT ... ON CONFLICT DO NOTHING<br/>(dedup)"]
    insert --> bloqueo{"¿IG muestra bloqueo?"}
    bloqueo -->|sí| stop(["FRENA EN SECO<br/>cambiar de cuenta a mano"])
    bloqueo -->|no| mas{"¿más por cargar<br/>y sin tope?"}
    mas -->|sí| scroll
    mas -->|"lista agotada"| completar["marcar seed completado"]
    mas -->|"tope alcanzado"| tocar["actualizar last_scan<br/>(pausado)"]
    completar --> loop
    tocar --> fin
```

---

## 3. Flujo de `worker_enrich` (calificar)

Toma perfiles `status=new` en lotes chicos, los visita una vez, extrae datos,
corre el scoring y guarda el verdict. Es el worker más caro y riesgoso.

```mermaid
flowchart TD
    inicio(["python worker_enrich.py"]) --> login{"¿sesión de IG activa?"}
    login -->|no| abort(["abortar · avisar"])
    login -->|sí| lote["obtener lote status=new<br/>(tope por cantidad)"]
    lote --> loop{"¿quedan perfiles<br/>en el lote?"}
    loop -->|no| fin(["reportar · terminar"])
    loop -->|sí| visit["abrir perfil"]
    visit --> bloqueo{"¿IG muestra bloqueo?"}
    bloqueo -->|sí| stop(["FRENA EN SECO"])
    bloqueo -->|no| existe{"¿el perfil existe?"}
    existe -->|no| unknown["verdict = unknown"]
    existe -->|sí| privado{"¿es privado?"}
    privado -->|sí| private["verdict = private"]
    privado -->|no| extraer["extraer name / bio /<br/>links / followers / email"]
    extraer --> score["scoring.py<br/>score + reason + sell_tickets"]
    score --> umbral{"¿score >= 10?"}
    umbral -->|sí| lead["verdict = lead"]
    umbral -->|no| disc["verdict = discarded_attendee"]

    unknown --> guardar["UPDATE status=scanned"]
    private --> guardar
    lead --> guardar
    disc --> guardar
    guardar --> espera["delay humano (rate.py)"]
    espera --> loop
```

---

## 4. Estados de una fila en `counts`

`status` (¿ya lo procesé?) y `verdict` (¿qué es?) son **columnas separadas**: un
privado es `status=scanned` + `verdict=private` sin perder el rastro de que ya se
revisó.

```mermaid
stateDiagram-v2
    [*] --> new: worker_following lo descubre
    new --> scanned: worker_enrich lo procesa
    new --> failed: error tecnico
    failed --> scanned: reintento exitoso
    scanned --> [*]: queda listo para consulta
```

Cuando una fila llega a `status=scanned`, su `verdict` es uno de:

| verdict | significado |
|---|---|
| `lead` | candidato real (`score >= 10`) |
| `discarded_attendee` | escaneado pero no califica |
| `private` | perfil privado (registrado para no re-visitarlo) |
| `unknown` | no existe / no se pudo leer |

---

## 5. Dependencias entre módulos

La lógica delicada (sesión, ritmo) y la configuración viven en módulos
compartidos; los workers quedan delgados. `scoring.py` y `rate.py` no dependen de
nada interno (fáciles de tunear/probar aislados).

```mermaid
flowchart BT
    config["config.py<br/>(DB, delays, topes, log)"]
    db["db.py<br/>(SQL crudo)"]
    session["session.py<br/>(Chrome + login)"]
    scoring["scoring.py<br/>(pesos / keywords)"]
    rate["rate.py<br/>(delays + bloqueo)"]
    wf["worker_following.py"]
    we["worker_enrich.py"]

    db --> config
    session --> config

    wf --> db
    wf --> session
    wf --> rate
    wf --> config

    we --> db
    we --> session
    we --> rate
    we --> scoring
    we --> config
```
