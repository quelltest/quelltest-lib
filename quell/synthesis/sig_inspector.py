"""
Signature inspection — reads function AST to generate valid test call stubs.
No LLM required. Pure static analysis.

Used by the rule engine to build real callable tests instead of TODO scaffolds.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
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
    is_async: bool = False  # True for async def functions
    is_classmethod: bool = False  # True for @classmethod / @validator / @field_validator

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

    # Class methods — prefer concrete (non-abstract) over abstract stubs.
    # When BaseAdapter.send is `raise NotImplementedError` and HTTPAdapter.send
    # is the real implementation, we want HTTPAdapter, not BaseAdapter.
    abstract_fallback: tuple[ast.FunctionDef | ast.AsyncFunctionDef, str] | None = None
    for cls_node in ast.walk(tree):
        if not isinstance(cls_node, ast.ClassDef):
            continue
        for item in cls_node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != func_name:
                continue
            if _is_abstract_stub(item):
                if abstract_fallback is None:
                    abstract_fallback = (item, cls_node.name)
            else:
                return _extract(item, class_name=cls_node.name)

    if abstract_fallback:
        return _extract(abstract_fallback[0], class_name=abstract_fallback[1])
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

_CLASSMETHOD_DECORATORS = frozenset(
    ("classmethod", "validator", "field_validator", "model_validator", "staticmethod")
)


def _is_classmethod_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id in _CLASSMETHOD_DECORATORS:
            return True
        if isinstance(d, ast.Call):
            func = d.func
            name = (
                func.id if isinstance(func, ast.Name) else
                func.attr if isinstance(func, ast.Attribute) else ""
            )
            if name in _CLASSMETHOD_DECORATORS:
                return True
    return False


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

    is_classmethod = _is_classmethod_node(node)
    return FuncSignature(
        name=node.name,
        params=params,
        return_annotation=_ann_str(node.returns),
        class_name=class_name,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_classmethod=is_classmethod,
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

    # Callable types
    if ann.startswith(("Callable", "typing.Callable")):
        return "lambda: None", [], []

    # Common stdlib types
    if ann in ("logging.LogRecord",):
        return "__import__('logging').LogRecord('test', 20, '', 0, 'msg', [], None)", [], []
    if ann in ("datetime.datetime", "datetime"):
        return "__import__('datetime').datetime(2024, 1, 1)", [], []
    if ann in ("datetime.date",):
        return "__import__('datetime').date(2024, 1, 1)", [], []
    if ann in ("datetime.timedelta",):
        return "__import__('datetime').timedelta(seconds=1)", [], []
    if ann in ("re.Pattern", "re.Pattern[str]"):
        return "__import__('re').compile('.*')", [], []

    # Guess from parameter name
    for key, stub in _NAME_STUBS:
        if key in name_lower:
            fixtures = ["tmp_path"] if "tmp_path" in stub else []
            unknown_list = [ann] if ann else []
            return stub, fixtures, unknown_list

    # Truly unknown custom type — use None, track in unknown_list for report
    unknown_list = [ann] if ann else []
    return "None", [], unknown_list


def _is_abstract_stub(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Return True if the function body is just `raise NotImplementedError`.

    Used to skip abstract base class methods and prefer concrete subclass
    implementations when multiple methods share the same name in a file.
    """
    real = [n for n in node.body if not isinstance(n, (ast.Expr, ast.Pass))]
    if len(real) != 1 or not isinstance(real[0], ast.Raise):
        return False
    exc = real[0].exc
    if exc is None:
        return False
    # raise NotImplementedError  OR  raise NotImplementedError(...)
    name = exc.id if isinstance(exc, ast.Name) else (
        exc.func.id if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) else None
    )
    return name == "NotImplementedError"
