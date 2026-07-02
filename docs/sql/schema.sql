-- ============================================================
-- Esquema  ·  outreach (<EL NEGOCIO>)
-- PostgreSQL 13+   ·   Raspberry Pi, red local
-- Ejecutar:  psql -U outreach -d outreach -f schema.sql
-- ============================================================

-- ------------------------------------------------------------
-- Trigger genérico: mantiene updated_at al día en cada UPDATE
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------
-- counts: candidatos descubiertos (worker_following)
--         y enriquecidos/calificados (worker_enrich)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS counts (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username      text        NOT NULL UNIQUE,          -- identidad IG (clave natural)
  name          text,
  bio           text,                                 -- descripción del perfil
  email         text,                                 -- si aparece en la bio
  external_link text,                                 -- link de bio (passline, linktree, etc.)
  followers     integer,
  sell_tickets  boolean     NOT NULL DEFAULT false,   -- true SOLO con link de ticketera conocida
  profile_type  text,                                 -- libre: "dj", "organizador", "dj, organizador"
  music_genre   text,                                 -- libre: "techno", "rock", null
  score         integer     NOT NULL DEFAULT 0,       -- 0–100 · umbral de lead = 10
  score_reason  text,                                 -- qué señales sumaron: "boletos+passline+dj"
  status        text        NOT NULL DEFAULT 'new'
                CONSTRAINT counts_status_chk
                CHECK (status IN ('new', 'scanned', 'failed')),  -- pipeline (crítico p/ coordinar workers)
  verdict       text,                                 -- lead | discarded_attendee | private | unknown (libre)
  message       text,                                 -- mensaje IA para copiar/pegar (fase posterior)
  seed_origen   text,                                 -- de qué seed salió
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- worker_enrich toma lotes FIFO de status='new' → índice parcial barato
CREATE INDEX IF NOT EXISTS counts_status_new_idx
  ON counts (created_at)
  WHERE status = 'new';

-- consulta final de leads: WHERE verdict='lead' AND score >= 10
CREATE INDEX IF NOT EXISTS counts_verdict_score_idx
  ON counts (verdict, score);

DROP TRIGGER IF EXISTS counts_set_updated_at ON counts;
CREATE TRIGGER counts_set_updated_at
  BEFORE UPDATE ON counts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ------------------------------------------------------------
-- seeds: perfiles ancla de los que se descubre (following)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seeds (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username   text        NOT NULL UNIQUE,
  name       text,
  completed  boolean     NOT NULL DEFAULT false,   -- true cuando se escaneó todo su círculo
  actived    boolean     NOT NULL DEFAULT true,    -- lo controla el humano; false = no se usa
  last_scan  timestamptz,                          -- para resume / saber cuándo se tocó
  created_at timestamptz NOT NULL DEFAULT now()
);

-- worker_following recorre seeds activas pendientes, las más viejas primero
CREATE INDEX IF NOT EXISTS seeds_active_pending_idx
  ON seeds (last_scan NULLS FIRST)
  WHERE actived = true AND completed = false;
