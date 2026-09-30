-- Tabla de estado de lampara-engine.
--
-- Fuente única de verdad. Nada de coordinar por archivos en una carpeta: si no está
-- aquí, no ha pasado. Cada parte de la cadena toca SOLO sus transiciones:
--
--   generador  pending -> generating -> generated
--   humano     generated -> approved
--   publisher  approved -> publishing -> published
--
-- El publisher reclama la fila de forma atómica con UPDATE ... RETURNING, para que
-- dos procesos no puedan publicar lo mismo. Verificado con SQLite 3.43.2.

PRAGMA journal_mode = WAL;      -- un lector no bloquea al escritor
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  creado_en          TEXT    NOT NULL DEFAULT (datetime('now')),

  -- qué se genera
  modo               TEXT    NOT NULL CHECK (modo IN ('replica','manual')),
  referencia         TEXT    NOT NULL,           -- id en assets/videos.json
  atrezzo            TEXT,                       -- id en marcas/brands.json; NULL en flujo A puro
  prompt_version     TEXT    NOT NULL,           -- ruta del prompt usado

  -- dónde y con qué
  proveedor          TEXT    NOT NULL CHECK (proveedor IN ('flashboards','fal')),
  job_proveedor      TEXT,                       -- su propio id, para rastrear en su panel

  -- estado
  estado             TEXT    NOT NULL DEFAULT 'pending'
                     CHECK (estado IN ('pending','generating','generated',
                                       'approved','publishing','published','failed')),

  -- dinero: los dos, porque el estimado es techo y el ratio se aprende midiéndolo
  coste_estimado_usd REAL,
  coste_usd          REAL,

  -- salida
  output_url         TEXT,                       -- URL pública del clip final
  audio_ref          TEXT,                       -- de qué referencia salió el audio montado.
                                                 -- NULL = el clip va mudo. El run 01 salió así.
  etiqueta_ia        INTEGER NOT NULL DEFAULT 0, -- 1 = lleva la etiqueta VISIBLE quemada.
  vertiente          TEXT NOT NULL DEFAULT 'con_caras'
                     CHECK (vertiente IN ('con_caras','sin_caras')),
                     -- con_caras exige etiqueta quemada; sin_caras se publica solo con
                     -- is_ai_generated, la etiqueta nativa de Instagram. Por defecto la
                     -- estricta: una pieza sin marcar no se cuela sin etiqueta.

  -- publicación
  caption            TEXT,
  hashtags           TEXT,
  plataforma         TEXT,
  post_id            TEXT UNIQUE,                -- UNIQUE: imposible registrar dos veces el mismo post
  post_url           TEXT,

  -- fallos
  error              TEXT,
  intentos           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado, creado_en);

-- Histórico por fase. Guarda el mensaje literal del proveedor y los params que
-- entraron con la respuesta que salió, para poder reconstruir qué pasó.
CREATE TABLE IF NOT EXISTS job_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  fase         TEXT    NOT NULL,
  estado       TEXT    NOT NULL CHECK (estado IN ('ok','error','running')),
  empezado_en  TEXT    NOT NULL DEFAULT (datetime('now')),
  acabado_en   TEXT,
  coste_usd    REAL,
  error_texto  TEXT,
  payload      TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id, id);

-- Lo que el humano tiene delante cuando va a aprobar.
CREATE VIEW IF NOT EXISTS pendientes_de_aprobar AS
  SELECT id, creado_en, modo, referencia, atrezzo, coste_usd, output_url, audio_ref
    FROM jobs WHERE estado = 'generated' ORDER BY creado_en;

-- Gasto por proveedor, y cuánto se desvía el estimado del real.
CREATE VIEW IF NOT EXISTS gasto AS
  SELECT proveedor,
         COUNT(*)                                        AS tiradas,
         ROUND(SUM(coste_estimado_usd), 4)               AS estimado,
         ROUND(SUM(coste_usd), 4)                        AS real,
         ROUND(SUM(coste_usd) / SUM(coste_estimado_usd), 3) AS ratio
    FROM jobs WHERE coste_usd IS NOT NULL GROUP BY proveedor;

-- ---------------------------------------------------------------------------
-- Una pieza, varias plataformas. jobs.post_id sirvió mientras solo existía
-- Instagram; una red necesita N publicaciones por job, cada una con su estado,
-- su caption y su desenlace. jobs.post_id se queda por compatibilidad con los
-- tres jobs ya publicados, pero lo que manda a partir de aquí es esta tabla.
CREATE TABLE IF NOT EXISTS publicaciones (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id),
  plataforma    TEXT NOT NULL
                CHECK (plataforma IN ('instagram','facebook','tiktok','youtube')),
  estado        TEXT NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente','publicando','publicado','fallida','omitida')),
  caption       TEXT,                    -- cada plataforma tiene su tono y sus límites
  audio_fuente  TEXT,                    -- de dónde salió la música QUE SE OYE ahí
  declara_ia    INTEGER NOT NULL DEFAULT 1,
  post_id       TEXT,
  post_url      TEXT,
  error         TEXT,
  creada_en     TEXT NOT NULL DEFAULT (datetime('now')),
  publicada_en  TEXT,
  UNIQUE (job_id, plataforma),           -- imposible publicar dos veces lo mismo en el mismo sitio
  UNIQUE (plataforma, post_id)
);

CREATE INDEX IF NOT EXISTS idx_pub_pendientes ON publicaciones(estado, plataforma);

-- ---------------------------------------------------------------------------
-- Métricas por publicación y por momento. Una fila por lectura, no una por
-- publicación: el valor de esto es la SERIE. A las 6 h se sabe si arrancó, a
-- las 48 h si aguantó. Sin la primera lectura no hay con qué comparar.
CREATE TABLE IF NOT EXISTS metricas (
  id             INTEGER PRIMARY KEY,
  publicacion_id INTEGER NOT NULL REFERENCES publicaciones(id),
  tomada_en      TEXT NOT NULL DEFAULT (datetime('now')),
  horas          REAL NOT NULL,              -- desde la publicación, para comparar manzanas
  alcance        INTEGER,
  visionados     INTEGER,
  interacciones  INTEGER,
  guardados      INTEGER,
  compartidos    INTEGER,
  comentarios    INTEGER,
  retencion_s    REAL,                       -- visionado medio en segundos
  crudo          TEXT,                       -- la respuesta entera, por si mañana medimos otra cosa
  fuente         TEXT NOT NULL DEFAULT 'api' -- api | navegador | manual
);

CREATE INDEX IF NOT EXISTS idx_metricas_pub ON metricas(publicacion_id, horas);

-- Confirmación posterior a publicar. Publicar y dar por hecho que salió bien es
-- lo que nos pasó el 27 sep: TikTok puso la pieza en «Solo yo» y Facebook se
-- quedó subiendo, y la tabla decía «publicado» en los dos casos.
--   ALTER TABLE publicaciones ADD COLUMN confirmada_en TEXT;
--   ALTER TABLE publicaciones ADD COLUMN verificacion  TEXT;
