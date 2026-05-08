"""
Signature inspection — reads function AST to generate valid test call stubs.
No LLM required. Pure static analysis.

Used by the rule engine to build real callable tests instead of TODO scaffolds.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParamInfo:
    name: str
    annotation: str | None
    has_default: bool


@dataclass
class FuncSignature:
    name: str
    params: list[ParamInfo]
    return_annotation: str | None
    class_name: str | None = None  # set when function is a class method

    @property
    def is_method(self) -> bool:
        return self.class_name is not None

    @property
    def callable_params(self) -> list[ParamInfo]:
        return [p for p in self.params if p.name not in ("self", "cls")]

    @property
    def required_params(self) -> list[ParamInfo]:
        return [p for p in self.callable_params if not p.has_default]

    @property
    def needs_tmp_path(self) -> bool:
        return any("Path" in (p.annotation or "") for p in self.callable_params)


# Exact annotation → stub value (no fixtures needed)
_SIMPLE_STUBS: dict[str, str] = {
    "str": '"test_value"',
    "int": "1",
    "float": "1.0",
    "bool": "True",
    "bytes": 'b"test"',
    "list": "[]",
    "dict": "{}",
    "tuple": "()",
    "set": "set()",
    "Any": '"test"',
    "None": "None",
    "type[str]": "str",
    "type[int]": "int",
}

# Parameter name keyword → stub (when no annotation available)
_NAME_STUBS: list[tuple[str, str]] = [
    ("path",      "tmp_path / 'test_file.py'"),
    ("file",      "tmp_path / 'test_file.py'"),
    ("dir",       "tmp_path"),
    ("directory", "tmp_path"),
    ("source",    '"def foo(): pass"'),
    ("code",      '"def foo(): pass"'),
    ("content",   '"test content"'),
    ("text",      '"test text"'),
    ("name",      '"test_name"'),
    ("key",       '"test_key"'),
    ("label",     '"test_label"'),
    ("message",   '"test message"'),
    ("msg",       '"test message"'),
    ("url",       '"http://localhost"'),
    ("host",      '"localhost"'),
    ("count",     "1"),
    ("num",       "1"),
    ("index",     "0"),
    ("size",      "1"),
    ("limit",     "10"),
    ("max",       "100"),
    ("min",       "0"),
    ("flag",      "False"),
    ("enabled",   "True"),
    ("disabled",  "False"),
    ("debug",     "False"),
    ("verbose",   "False"),
    ("force",     "False"),
    ("config",    "{}"),
    ("options",   "{}"),
    ("settings",  "{}"),
    ("kwargs",    "{}"),
    ("data",      "{}"),
    ("items",     "[]"),
    ("values",    "[]"),
    ("files",     "[]"),
    ("results",   "[]"),
    ("args",      "[]"),
]


def inspect(func_name: str, source_file: Path) -> FuncSignature | None:
    """Return the signature of func_name found in source_file, or None."""
    try:
        source = source_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return None

    # Module-level functions first
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return _extract(node, class_name=None)

    # Class methods
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == func_name:
                        return _extract(item, class_name=node.name)

    return None


def inspect_init(class_name: str, source_file: Path) -> FuncSignature | None:
    """Return the __init__ signature for class_name, or None."""
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == "__init__":
                        return _extract(item, class_name=class_name)
            # No explicit __init__ — class takes no args
            return FuncSignature(
                name="__init__", params=[], return_annotation=None,
                class_name=class_name
            )
    return None


def module_path(source_file: Path) -> str:
    """Derive dotted Python module path from a .py file path.

    Walks up as long as __init__.py exists in each directory.
    E.g.  refactron/config/loader.py  →  refactron.config.loader
    """
    parts: list[str] = [source_file.stem]
    current = source_file.parent

    while (current / "__init__.py").exists():
        parts.insert(0, current.name)
        current = current.parent

    return ".".join(parts)


def find_project_root(source_file: Path) -> Path:
    """Walk up from source_file to find pyproject.toml / setup.py / setup.cfg."""
    markers = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini"}
    current = source_file.parent
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent
    return source_file.parent


def stub_for_call(sig: FuncSignature) -> tuple[str, list[str], list[str]]:
    """Build call argument string for required parameters.

    Returns:
        args_str      -- e.g. 'file_path=tmp_path / "x.py", count=1'
        fixtures      -- pytest fixture names needed, e.g. ['tmp_path']
        unknown_types -- annotation strings the inspector couldn't stub
    """
    args: list[str] = []
    fixtures: list[str] = []
    unknown: list[str] = []

    for p in sig.required_params:
        stub, fix, unk = _stub_param(p)
        args.append(f"{p.name}={stub}")
        fixtures.extend(fix)
        unknown.extend(unk)

    return ", ".join(args), list(dict.fromkeys(fixtures)), unknown


# ── internals ────────────────────────────────────────────────────────────────

def _extract(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str | None,
) -> FuncSignature:
    args = node.args
    params: list[ParamInfo] = []
    n_args = len(args.args)
    n_defaults = len(args.defaults)

    for i, arg in enumerate(args.args):
        has_default = i >= (n_args - n_defaults)
        params.append(ParamInfo(
            name=arg.arg,
            annotation=_ann_str(arg.annotation),
            has_default=has_default,
        ))

    return FuncSignature(
        name=node.name,
        params=params,
        return_annotation=_ann_str(node.returns),
        class_name=class_name,
    )


def _ann_str(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _stub_param(p: ParamInfo) -> tuple[str, list[str], list[str]]:
    """Return (stub_value, fixtures_needed, unknown_types)."""
    ann = (p.annotation or "").strip()
    name_lower = p.name.lower()

    # Exact match
    if ann in _SIMPLE_STUBS:
        return _SIMPLE_STUBS[ann], [], []

    # Optional[X] or X | None → None
    if ann.startswith(("Optional[", "typing.Optional[")):
        return "None", [], []
    if "|" in ann and "None" in ann.split("|"):
        return "None", [], []

    # Path variants
    if "Path" in ann:
        return "tmp_path / 'test_file.py'", ["tmp_path"], []

    # Generic collections
    if ann.startswith(("List[", "list[", "Sequence[", "Iterable[")):
        return "[]", [], []
    if ann.startswith(("Dict[", "dict[", "Mapping[", "MutableMapping[")):
        return "{}", [], []
    if ann.startswith(("Tuple[", "tuple[")):
        return "()", [], []
    if ann.startswith(("Set[", "set[", "FrozenSet[", "frozenset[")):
        return "set()", [], []

    # Primitive subtype (e.g. "FileName(str)")
    ann_lower = ann.lower()
    if ann_lower in ("str", "string") or (ann_lower.endswith("str") and len(ann) < 12):
        return '"test_value"', [], []
    if ann_lower in ("int", "integer") or (ann_lower.endswith("int") and len(ann) < 12):
        return "1", [], []
    if ann_lower == "float":
        return "1.0", [], []
    if ann_lower == "bool":
        return "True", [], []

    # Guess from parameter name
    for key, stub in _NAME_STUBS:
        if key in name_lower:
            fixtures = ["tmp_path"] if "tmp_path" in stub else []
            unknown_list = [ann] if ann else []
            return stub, fixtures, unknown_list

    # Truly unknown custom type
    unknown_list = [ann] if ann else []
    return "None  # unknown: provide a valid instance", [], unknown_list
