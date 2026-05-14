"""Detect framework route decorators (FastAPI, Flask) on functions.

Used so the rule engine doesn't waste cycles stub-testing route handlers —
those go through a TestClient-based engine instead.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

FASTAPI_HTTP_METHODS = frozenset(
    ("get", "post", "put", "patch", "delete", "head", "options")
)


@dataclass
class RouteInfo:
    framework: str       # "fastapi" | "flask"
    method: str          # "GET", "POST", ...
    path: str            # "/users/{user_id}"
    function_name: str
    is_async: bool


def detect_route(func_name: str, source_file: Path) -> RouteInfo | None:
    """Return RouteInfo if func_name has a FastAPI/Flask route decorator, else None."""
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        is_async = isinstance(node, ast.AsyncFunctionDef)
        for dec in node.decorator_list:
            info = _parse_fastapi(dec, node.name, is_async)
            if info:
                return info
            info = _parse_flask(dec, node.name, is_async)
            if info:
                return info
    return None


def _parse_fastapi(
    dec: ast.expr, fname: str, is_async: bool
) -> RouteInfo | None:
    """@router.get("/path") | @app.post("/path") | similar."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr.lower()
    if method not in FASTAPI_HTTP_METHODS:
        return None
    if not dec.args:
        return None
    first = dec.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    return RouteInfo("fastapi", method.upper(), first.value, fname, is_async)


def _parse_flask(
    dec: ast.expr, fname: str, is_async: bool
) -> RouteInfo | None:
    """@app.route("/path", methods=["POST"])."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute) or func.attr != "route":
        return None
    if not dec.args:
        return None
    first = dec.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    method = "GET"
    for kw in dec.keywords:
        if kw.arg != "methods" or not isinstance(kw.value, ast.List):
            continue
        for elt in kw.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                method = elt.value.upper()
                break
        break
    return RouteInfo("flask", method, first.value, fname, is_async)
