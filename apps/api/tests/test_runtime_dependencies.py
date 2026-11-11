"""Every third-party module the app imports must be a runtime dependency.

Production installs only [project].dependencies, not the dev group. A module
that is only in the dev group passes every local test and then crashes the
deployed API at import time (this happened with httpx on Vercel).
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, packages_distributions, requires
from pathlib import Path

from packaging.requirements import Requirement

API_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = API_ROOT / "app"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _imported_top_level_modules() -> set[str]:
    modules: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return {m for m in modules if m != "app" and m not in sys.stdlib_module_names}


def _runtime_distributions() -> set[str]:
    """Runtime dependencies plus everything they pull in (what production installs)."""
    project = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pending = [Requirement(r) for r in project["project"]["dependencies"]]
    seen: set[str] = set()
    while pending:
        req = pending.pop()
        name = _norm(req.name)
        if name in seen:
            continue
        seen.add(name)
        try:
            sub_requirements = requires(req.name) or []
        except PackageNotFoundError:
            continue
        for raw in sub_requirements:
            sub = Requirement(raw)
            env = {"extra": ""}
            wanted = (
                sub.marker is None
                or sub.marker.evaluate(env)
                or any(sub.marker.evaluate({"extra": extra}) for extra in req.extras)
            )
            if wanted:
                pending.append(sub)
    return seen


def test_every_imported_module_is_installed_in_production() -> None:
    module_to_dists = packages_distributions()
    runtime = _runtime_distributions()

    missing = {}
    for module in _imported_top_level_modules():
        dists = module_to_dists.get(module, [])
        if not any(_norm(d) in runtime for d in dists):
            missing[module] = dists

    assert not missing, (
        f"Imported by app/ but not installed in production: {missing}. "
        "Add them to [project].dependencies in apps/api/pyproject.toml."
    )
