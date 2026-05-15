"""
QuellGraph incremental AST builder.

Walks a project directory and populates the SQLite graph.
Only re-parses files whose sha256 hash has changed since the last build.
"""
from __future__ import annotations

import ast
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1"
_SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# Import signals are defined here to keep builder self-contained.
# quell.infra.specs has the canonical copy; this mirrors it so graph
# can be used without the infra optional-dependency being present.
_IMPORT_SIGNALS: dict[str, str] = {
    "sqlalchemy": "postgres", "databases": "postgres", "asyncpg": "postgres",
    "psycopg2": "postgres", "psycopg": "postgres", "tortoise": "postgres",
    "alembic": "postgres", "pymysql": "mysql", "aiomysql": "mysql",
    "motor": "mongo", "pymongo": "mongo", "beanie": "mongo",
    "redis": "redis", "aioredis": "redis", "celery": "redis", "kombu": "redis",
    "boto3": "localstack", "botocore": "localstack", "aiobotocore": "localstack",
    "s3fs": "localstack", "elasticsearch": "elasticsearch",
    "opensearchpy": "opensearch", "pika": "rabbitmq", "aio_pika": "rabbitmq",
    "smtplib": "smtp", "aiosmtplib": "smtp",
}

_INFRA_TYPE_NAMES: dict[str, str] = {
    "Session": "postgres", "AsyncSession": "postgres",
    "Connection": "postgres", "AsyncConnection": "postgres",
    "Redis": "redis", "StrictRedis": "redis", "AsyncRedis": "redis",
    "MongoClient": "mongo", "AsyncIOMotorClient": "mongo",
    "S3Client": "localstack", "DynamoDBClient": "localstack",
    "Elasticsearch": "elasticsearch",
    "BlockingConnection": "rabbitmq", "Channel": "rabbitmq",
}


@dataclass
class BuildReport:
    """Summary of a QuellGraph build run."""

    total_files: int
    reparsed: int
    functions: int
    classes: int
    build_time_ms: float = 0.0


class QuellGraphBuilder:
    """
    Walks a project directory and populates the SQLite graph.
    Incremental: only re-parses files whose sha256 hash has changed.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, project_root: Path) -> BuildReport:
        """Full incremental build. Returns a BuildReport."""
        start = time.time()
        files = [
            f for f in project_root.rglob("*.py")
            if not any(part.startswith(".") for part in f.parts)
            and "__pycache__" not in f.parts
        ]
        changed = self._find_changed(files)

        for f in changed:
            try:
                source = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(f))
            except SyntaxError:
                logger.debug("QuellGraph: skipping unparseable file %s", f)
                continue
            self._index_module(f, tree, source)
            self._index_functions(f, tree)
            self._index_classes(f, tree)
            self._index_calls(f, tree)

        self._resolve_calls()
        self._propagate_infra_tags()
        self._compute_purity()
        self._compute_annotation_coverage()

        self._conn.execute(
            "INSERT OR REPLACE INTO graph_meta VALUES (?,?)",
            ("last_full_scan", str(time.time())),
        )
        self._conn.commit()

        elapsed = (time.time() - start) * 1000
        return BuildReport(
            total_files=len(files),
            reparsed=len(changed),
            functions=self._count("functions"),
            classes=self._count("classes"),
            build_time_ms=round(elapsed, 1),
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        schema = _SCHEMA_FILE.read_text(encoding="utf-8")
        self._conn.executescript(schema)
        cur = self._conn.execute(
            "SELECT value FROM graph_meta WHERE key='schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO graph_meta VALUES (?,?)", ("schema_version", _SCHEMA_VERSION)
            )
            self._conn.commit()

    def _find_changed(self, files: list[Path]) -> list[Path]:
        """Return only files whose sha256 hash differs from the stored hash."""
        changed = []
        for f in files:
            try:
                h = sha256(f.read_bytes()).hexdigest()
            except OSError:
                continue
            row = self._conn.execute(
                "SELECT file_hash FROM modules WHERE file=?", (str(f),)
            ).fetchone()
            if row is None or row["file_hash"] != h:
                changed.append(f)
        return changed

    def _file_hash(self, f: Path) -> str:
        return sha256(f.read_bytes()).hexdigest()

    def _index_module(self, f: Path, tree: ast.Module, source: str) -> None:
        h = self._file_hash(f)
        package = f.parts[0] if f.parts else ""
        imports: list[dict[str, Any]] = []
        infra_tags: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    tag = _IMPORT_SIGNALS.get(top)
                    imports.append({
                        "module": alias.name, "alias": alias.asname,
                        "from_name": None, "lineno": node.lineno,
                    })
                    if tag and tag not in infra_tags:
                        infra_tags.append(tag)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                tag = _IMPORT_SIGNALS.get(top)
                imports.append({
                    "module": node.module, "alias": None,
                    "from_name": [a.name for a in node.names],
                    "lineno": node.lineno,
                })
                if tag and tag not in infra_tags:
                    infra_tags.append(tag)

        self._conn.execute(
            """INSERT OR REPLACE INTO modules
               (id, file, package, imports, infra_tags, file_hash, parsed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (str(f), str(f), package,
             json.dumps(imports), json.dumps(infra_tags),
             h, time.time()),
        )

        # Upsert import edges
        self._conn.execute("DELETE FROM imports WHERE module_id=?", (str(f),))
        for tag in infra_tags:
            top_pkg = next(
                (k for k, v in _IMPORT_SIGNALS.items() if v == tag), tag
            )
            self._conn.execute(
                "INSERT INTO imports (module_id, package, infra_tag) VALUES (?,?,?)",
                (str(f), top_pkg, tag),
            )

    def _fn_id(self, f: Path, name: str, lineno: int) -> str:
        return sha256(f"{f}:{name}:{lineno}".encode()).hexdigest()

    def _index_functions(self, f: Path, tree: ast.Module) -> None:
        h = self._file_hash(f)
        # Delete stale rows for this file
        self._conn.execute("DELETE FROM functions WHERE file=?", (str(f),))
        self._conn.execute("DELETE FROM param_types WHERE function_id IN "
                           "(SELECT id FROM functions WHERE file=?)", (str(f),))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            fn_id = self._fn_id(f, node.name, node.lineno)
            docstring = ast.get_docstring(node) or None
            has_raises = docstring is not None and "Raises:" in docstring if docstring else False
            has_returns = docstring is not None and "Returns:" in docstring if docstring else False
            has_args = docstring is not None and "Args:" in docstring if docstring else False

            params = [
                a for a in node.args.args
                if a.arg not in ("self", "cls")
            ]

            # Detect decorators
            deco_names = {
                (d.id if isinstance(d, ast.Name) else
                 (d.attr if isinstance(d, ast.Attribute) else ""))
                for d in node.decorator_list
            }
            is_classmethod = "classmethod" in deco_names
            is_staticmethod = "staticmethod" in deco_names
            is_property = "property" in deco_names

            # Signature text
            try:
                sig = ast.unparse(node).split("\n")[0]
            except Exception:
                sig = f"def {node.name}(...)"

            self._conn.execute(
                """INSERT OR REPLACE INTO functions
                   (id, name, file, line_start, line_end, signature, docstring,
                    is_async, is_method, is_classmethod, is_staticmethod, is_property,
                    has_docstring, has_raises_block, has_returns_block, has_args_block,
                    param_count, file_hash, parsed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fn_id, node.name, str(f),
                 node.lineno, node.end_lineno or node.lineno,
                 sig, docstring,
                 int(isinstance(node, ast.AsyncFunctionDef)),
                 0, int(is_classmethod), int(is_staticmethod), int(is_property),
                 int(bool(docstring)),
                 int(has_raises), int(has_returns), int(has_args),
                 len(params), h, time.time()),
            )

            # Index param types
            for arg in node.args.args:
                if arg.arg in ("self", "cls"):
                    continue
                type_str = ast.unparse(arg.annotation) if arg.annotation else None
                infra_tag = _INFRA_TYPE_NAMES.get(type_str or "") if type_str else None
                self._conn.execute(
                    """INSERT INTO param_types
                       (function_id, param_name, type_str, is_typed, is_infra_type, infra_tag)
                       VALUES (?,?,?,?,?,?)""",
                    (fn_id, arg.arg, type_str,
                     int(type_str is not None),
                     int(infra_tag is not None),
                     infra_tag),
                )

    def _index_classes(self, f: Path, tree: ast.Module) -> None:
        h = self._file_hash(f)
        self._conn.execute("DELETE FROM classes WHERE file=?", (str(f),))

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            cls_id = sha256(f"{f}:{node.name}:{node.lineno}".encode()).hexdigest()
            base_names = [
                (b.id if isinstance(b, ast.Name) else
                 (ast.unparse(b)))
                for b in node.bases
            ]
            is_pydantic = any(
                "BaseModel" in b or "pydantic" in b for b in base_names
            )
            is_dataclass = any(
                (d.id if isinstance(d, ast.Name) else
                 (d.attr if isinstance(d, ast.Attribute) else "")) == "dataclass"
                for d in node.decorator_list
            )

            self._conn.execute(
                """INSERT OR REPLACE INTO classes
                   (id, name, file, line_start, line_end,
                    bases, is_pydantic, is_dataclass, file_hash, parsed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (cls_id, node.name, str(f),
                 node.lineno, node.end_lineno or node.lineno,
                 json.dumps(base_names),
                 int(is_pydantic), int(is_dataclass), h, time.time()),
            )

    def _index_calls(self, f: Path, tree: ast.Module) -> None:
        self._conn.execute(
            "DELETE FROM calls WHERE caller_id IN "
            "(SELECT id FROM functions WHERE file=?)", (str(f),)
        )
        # Map name→fn_id for functions in this file
        fn_map: dict[str, str] = {
            row["name"]: row["id"]
            for row in self._conn.execute(
                "SELECT id, name FROM functions WHERE file=?", (str(f),)
            )
        }

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller_id = fn_map.get(node.name)
            if caller_id is None:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                callee_name = _extract_call_name(child)
                if callee_name:
                    self._conn.execute(
                        """INSERT INTO calls (caller_id, callee_name, line, is_resolved)
                           VALUES (?,?,?,0)""",
                        (caller_id, callee_name,
                         getattr(child, "lineno", 0)),
                    )

    def _resolve_calls(self) -> None:
        """Match callee_name strings to functions.id across the graph."""
        name_to_id: dict[str, str] = {
            row["name"]: row["id"]
            for row in self._conn.execute("SELECT id, name FROM functions")
        }
        for row in self._conn.execute(
            "SELECT rowid, callee_name FROM calls WHERE is_resolved=0"
        ):
            callee_id = name_to_id.get(row["callee_name"])
            if callee_id:
                self._conn.execute(
                    "UPDATE calls SET callee_id=?, is_resolved=1 WHERE rowid=?",
                    (callee_id, row["rowid"]),
                )

    def _propagate_infra_tags(self) -> None:
        """
        BFS from leaf nodes upward through call edges.
        If function B has infra_tag=postgres and A calls B, A inherits postgres.
        """
        # Seed: functions that have direct infra tags via param types or module imports
        fn_tags: dict[str, set[str]] = {}

        # From param types
        for row in self._conn.execute(
            "SELECT function_id, infra_tag FROM param_types WHERE is_infra_type=1"
        ):
            fn_tags.setdefault(row["function_id"], set()).add(row["infra_tag"])

        # From module-level imports
        for row in self._conn.execute("SELECT id, file, infra_tags FROM functions"):
            module_row = self._conn.execute(
                "SELECT infra_tags FROM modules WHERE file=?", (row["file"],)
            ).fetchone()
            if module_row and module_row["infra_tags"]:
                tags = json.loads(module_row["infra_tags"])
                if tags:
                    fn_tags.setdefault(row["id"], set()).update(tags)

        # BFS propagation upward through call edges (callee → caller)
        changed = True
        while changed:
            changed = False
            for row in self._conn.execute(
                "SELECT caller_id, callee_id FROM calls WHERE is_resolved=1"
            ):
                callee_tags = fn_tags.get(row["callee_id"], set())
                if not callee_tags:
                    continue
                before = fn_tags.get(row["caller_id"], set()).copy()
                fn_tags.setdefault(row["caller_id"], set()).update(callee_tags)
                if fn_tags[row["caller_id"]] != before:
                    changed = True

        # Write back
        for fn_id, tags in fn_tags.items():
            self._conn.execute(
                "UPDATE functions SET infra_tags=? WHERE id=?",
                (json.dumps(sorted(tags)), fn_id),
            )

    def _compute_purity(self) -> None:
        """Set is_pure + purity_score: 1.0 = no infra deps, 0.0 = heavy I/O."""
        for row in self._conn.execute("SELECT id, infra_tags FROM functions"):
            tags = json.loads(row["infra_tags"] or "[]")
            is_pure = int(len(tags) == 0)
            score = 1.0 if is_pure else max(0.0, 1.0 - len(tags) * 0.2)
            self._conn.execute(
                "UPDATE functions SET is_pure=?, purity_score=? WHERE id=?",
                (is_pure, round(score, 2), row["id"]),
            )

    def _compute_annotation_coverage(self) -> None:
        """Set annotation_coverage = typed_slots / total_slots per function."""
        for row in self._conn.execute("SELECT id, param_count FROM functions"):
            typed = self._conn.execute(
                "SELECT COUNT(*) FROM param_types WHERE function_id=? AND is_typed=1",
                (row["id"],),
            ).fetchone()[0]
            total = row["param_count"] + 1  # +1 for return type
            coverage = round(typed / total, 2) if total > 0 else 0.0
            self._conn.execute(
                "UPDATE functions SET annotation_coverage=? WHERE id=?",
                (coverage, row["id"]),
            )

    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_call_name(call: ast.Call) -> str | None:
    """Extract a best-effort name string from a Call node."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
