"""app/requirements.txt (read by Streamlit Community Cloud) must stay in sync with requirements-app.txt.

Checks that (1) every pin in app/requirements.txt matches requirements-app.txt exactly, and
(2) app/requirements.txt lists exactly the third-party distributions the app imports, found by
walking the import closure of app/streamlit_app.py through the repo's own packages.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_PACKAGES = {"labcore", "synth", "network", "exchange", "measures", "app", "sitegen", "tests"}
# Import name -> distribution(s) to install. An import missing here fails the test on purpose,
# so a new app dependency is added to both requirement files deliberately.
MODULE_TO_DIST = {
    "duckdb": {"duckdb"},
    "fastapi": {"fastapi"},
    # FastAPI's TestClient is Starlette's; Starlette 1.10 imports httpx2 (httpx is a deprecated fallback).
    # Starlette is pinned because FastAPI only requires starlette>=0.46.0.
    "fastapi.testclient": {"httpx2", "starlette"},
    "pandas": {"pandas"},
    "plotly": {"plotly"},
    "streamlit": {"streamlit"},
}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            pins.update(parse_requirements(path.parent / line[3:].strip()))
            continue
        name, sep, version = line.partition("==")
        assert sep, f"{path.name}: '{line}' must be pinned with =="
        pins[_norm(name)] = version.strip()
    return pins


def _module_file(module: str) -> list[Path]:
    p = ROOT.joinpath(*module.split("."))
    return [c for c in (p.with_suffix(".py"), p / "__init__.py") if c.exists()]


def app_third_party_imports() -> set[str]:
    todo, seen, found = [ROOT / "app" / "streamlit_app.py"], set(), set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        pkg = ".".join(f.relative_to(ROOT).parent.parts)
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = f"{pkg}.{base}".rstrip(".")
                mods = [base] + [f"{base}.{a.name}" for a in node.names]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                if top in LOCAL_PACKAGES:
                    todo += _module_file(m)
                elif top not in sys.stdlib_module_names and top != "__future__":
                    found.add(m)
    return found


def required_distributions() -> set[str]:
    dists, unknown = set(), set()
    for m in app_third_party_imports():
        parts = m.split(".")
        keys = [
            ".".join(parts[:i]) for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in MODULE_TO_DIST
        ]
        if not keys:
            unknown.add(m)
        for k in keys:
            dists |= MODULE_TO_DIST[k]
    assert not unknown, (
        f"App imports with no distribution mapping (update MODULE_TO_DIST + both files): {unknown}"
    )
    return {_norm(d) for d in dists}


def test_app_pins_match_requirements_app():
    app = parse_requirements(ROOT / "app" / "requirements.txt")
    full = parse_requirements(ROOT / "requirements-app.txt")
    mismatched = {k: (v, full.get(k)) for k, v in app.items() if full.get(k) != v}
    assert not mismatched, f"app/requirements.txt pins differ from requirements-app.txt: {mismatched}"


def test_app_requirements_are_exactly_the_app_dependencies():
    app = set(parse_requirements(ROOT / "app" / "requirements.txt"))
    need = required_distributions()
    assert app == need, f"missing: {sorted(need - app)}; not imported by the app: {sorted(app - need)}"


def test_app_requirements_has_no_includes():
    """Cloud resolves the file from app/, so no `-r` includes of root files."""
    text = (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")
    assert not any(line.strip().startswith("-r") for line in text.splitlines())
