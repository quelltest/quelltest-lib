"""Locate the FastAPI/Flask app instance in a project.

So generated TestClient tests can do `from {module} import {attr}`.
Best-effort — returns None if the heuristics fail; the caller should
then skip framework synthesis with a clear message.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppInfo:
    framework: str       # "fastapi" | "flask"
    module_path: str     # "app.main"
    attr_name: str       # "app"
    file_path: Path


def find_app(project_root: Path) -> AppInfo | None:
    """Walk project_root looking for `app = FastAPI(...)` or `app = Flask(...)`.

    Returns the first match. Prefers files named main.py/app.py/api.py if
    multiple candidates exist.
    """
    if not project_root.exists():
        return None

    candidates: list[AppInfo] = []
    for py in project_root.rglob("*.py"):
        s = str(py)
        if any(skip in s for skip in (".venv", "site-packages", "__pycache__", "/tests/", "\\tests\\")):
            continue
        info = _scan_file(py, project_root)
        if info:
            candidates.append(info)

    if not candidates:
        return None

    # Prefer common entrypoint filenames
    preferred = {"main.py", "app.py", "api.py", "server.py", "asgi.py", "wsgi.py"}
    for c in candidates:
        if c.file_path.name in preferred:
            return c
    return candidates[0]


def _scan_file(path: Path, project_root: Path) -> AppInfo | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    for node in tree.body:
        # Match: name = FastAPI(...)  /  name = Flask(...)
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        called = value.func
        called_name = (
            called.id if isinstance(called, ast.Name)
            else called.attr if isinstance(called, ast.Attribute)
            else None
        )
        if called_name == "FastAPI":
            framework = "fastapi"
        elif called_name == "Flask":
            framework = "flask"
        else:
            continue
        module_path = _module_path(path, project_root)
        return AppInfo(framework, module_path, target.id, path)
    return None


def _module_path(file_path: Path, project_root: Path) -> str:
    """Derive a dotted module path relative to project_root.

    Walk up while __init__.py exists; if the walk reaches project_root
    without hitting a non-package boundary, use the relative path from
    project_root as the module path.
    """
    parts: list[str] = [file_path.stem]
    current = file_path.parent
    while (current / "__init__.py").exists() and current != project_root:
        parts.insert(0, current.name)
        current = current.parent
    return ".".join(parts)
