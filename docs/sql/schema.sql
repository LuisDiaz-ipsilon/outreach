counts (
  username        text  UNIQUE NOT NULL
  name            text  NULL
  bio             text  NULL
  email           text  NULL
  external_link   text  NULL          -- link de bio (passline, linktree, etc.)
  followers       int   NULL
  sell_tickets    bool  DEFAULT false -- true solo si hay link de ticketera conocida
  profile_type    text  NULL          -- libre: "dj", "organizador", "dj, organizador"
  music_genre     text  NULL          -- libre: "techno", "rock", null
  score           int   DEFAULT 0
  score_reason    text  NULL          -- qué señales sumaron: "boletos+passline+dj"
  status          text  DEFAULT 'new' -- new | scanned | failed
  verdict         text  NULL          -- lead | discarded_attendee | private | unknown
  message         text  NULL          -- mensaje IA para copiar/pegar
  seed_origen     text  NULL          -- de qué seed salió
  created_at      timestamptz DEFAULT now()
  updated_at      timestamptz DEFAULT now()
)

seeds (
  username    text  UNIQUE NOT NULL
  name        text  NULL
  completed   bool  DEFAULT false  -- true cuando se escaneó todo su círculo
  actived     bool  DEFAULT true   -- tú lo controlas; false = no se usa
  last_scan   timestamptz NULL     -- para resume / saber cuándo se tocó
)