-- QuellGraph SQLite schema v1
-- Location: .quellgraph/graph.db
-- Atomic writes via graph.db.tmp + rename.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Meta
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS graph_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- keys: schema_version, project_root, last_full_scan, quelltest_version

-- ---------------------------------------------------------------------------
-- Nodes: Functions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS functions (
    id                   TEXT PRIMARY KEY,   -- sha256(filepath:name:lineno)
    name                 TEXT NOT NULL,
    qualified_name       TEXT,               -- module.ClassName.method_name
    file                 TEXT NOT NULL,
    line_start           INTEGER,
    line_end             INTEGER,
    signature            TEXT,               -- full def line source
    docstring            TEXT,
    is_async             INTEGER DEFAULT 0,  -- BOOLEAN
    is_method            INTEGER DEFAULT 0,
    is_classmethod       INTEGER DEFAULT 0,
    is_staticmethod      INTEGER DEFAULT 0,
    is_property          INTEGER DEFAULT 0,
    is_pure              INTEGER,            -- computed: no I/O in transitive closure
    purity_score         REAL,              -- 0.0 (heavy I/O) to 1.0 (pure)
    annotation_coverage  REAL,             -- typed slots / total slots
    has_docstring        INTEGER DEFAULT 0,
    has_raises_block     INTEGER DEFAULT 0,
    has_returns_block    INTEGER DEFAULT 0,
    has_args_block       INTEGER DEFAULT 0,
    param_count          INTEGER DEFAULT 0,
    infra_tags           TEXT,              -- JSON: ["postgres","redis"] transitive
    direct_infra_tags    TEXT,             -- JSON: tags from this file's imports only
    file_hash            TEXT,
    parsed_at            REAL
);

-- ---------------------------------------------------------------------------
-- Nodes: Classes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classes (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    file         TEXT NOT NULL,
    line_start   INTEGER,
    line_end     INTEGER,
    bases        TEXT,                     -- JSON list of base class names
    is_pydantic  INTEGER DEFAULT 0,
    is_dataclass INTEGER DEFAULT 0,
    fields       TEXT,                    -- JSON: [{name,type,has_validator,default}]
    file_hash    TEXT,
    parsed_at    REAL
);

-- ---------------------------------------------------------------------------
-- Nodes: Modules
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS modules (
    id          TEXT PRIMARY KEY,          -- absolute normalised file path
    file        TEXT NOT NULL UNIQUE,
    package     TEXT,                      -- top-level package name
    imports     TEXT,                      -- JSON: [{module,alias,from_name,lineno}]
    infra_tags  TEXT,                      -- JSON: direct tags from this module's imports
    file_hash   TEXT,
    parsed_at   REAL
);

-- ---------------------------------------------------------------------------
-- Nodes: External dep registry (import name → infra tag)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS external_deps (
    package         TEXT PRIMARY KEY,
    infra_tag       TEXT,                  -- "postgres" | "redis" | "localstack" | null
    import_examples TEXT                   -- JSON: list of raw import strings seen
);

-- ---------------------------------------------------------------------------
-- Edges: Function calls
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calls (
    caller_id    TEXT NOT NULL,            -- functions.id
    callee_id    TEXT,                     -- functions.id (null if external/unresolved)
    callee_name  TEXT NOT NULL,            -- raw name as written in source
    line         INTEGER,
    is_resolved  INTEGER DEFAULT 0,        -- BOOLEAN
    FOREIGN KEY (caller_id) REFERENCES functions(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Edges: Module imports
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS imports (
    module_id    TEXT NOT NULL,            -- modules.id
    package      TEXT NOT NULL,            -- top-level package
    full_import  TEXT,                     -- "from sqlalchemy.orm import Session"
    infra_tag    TEXT,
    FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Edges: Class inheritance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inherits (
    child_id     TEXT NOT NULL,
    parent_name  TEXT NOT NULL,
    parent_id    TEXT,                     -- null if external (e.g. BaseModel)
    FOREIGN KEY (child_id) REFERENCES classes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Edges: Function uses Pydantic model
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uses_model (
    function_id  TEXT NOT NULL,
    class_id     TEXT NOT NULL,
    usage_kind   TEXT,                    -- "param_type" | "return_type" | "instantiated"
    FOREIGN KEY (function_id) REFERENCES functions(id) ON DELETE CASCADE,
    FOREIGN KEY (class_id)    REFERENCES classes(id)   ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Edges: Parameter type annotations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS param_types (
    function_id   TEXT NOT NULL,
    param_name    TEXT NOT NULL,
    type_str      TEXT,
    is_typed      INTEGER DEFAULT 0,
    is_infra_type INTEGER DEFAULT 0,       -- e.g. Session, Redis, AsyncSession
    infra_tag     TEXT,
    FOREIGN KEY (function_id) REFERENCES functions(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_functions_file  ON functions(file);
CREATE INDEX IF NOT EXISTS idx_functions_name  ON functions(name);
CREATE INDEX IF NOT EXISTS idx_calls_caller    ON calls(caller_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee    ON calls(callee_id);
CREATE INDEX IF NOT EXISTS idx_imports_package ON imports(package);
