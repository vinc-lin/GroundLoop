"""CI contract: the product runtime must not MODULE-import any labs package (Core/Labs boundary).
Function-local imports are the sanctioned opt-in seam (the cli's lazy arm/KB/produce/grade loads)."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "groundloop"
PRODUCT_DIRS = ["core", "config", "adapters", "domains", "run", "fix", "engines/atlas", "engines/lore"]
# labs subtrees that physically live under a product dir -> excluded from the product scan
EXCLUDE = [ROOT / "adapters" / "index" / "labs"]
FORBIDDEN = ("groundloop.eval", "groundloop.fixeval", "groundloop.funceval", "groundloop.faulteval",
             "groundloop.synth", "groundloop.mine", "groundloop.kb", "groundloop.skills",
             "groundloop.grade", "groundloop.build", "groundloop.adapters.index.labs",
             "codewiki")


def _eager_imports(py):
    """Modules imported EAGERLY (at import time): module-level or inside a top-level if/try/with, but NOT
    inside a function/method (function-local imports are the sanctioned lazy opt-in seam)."""
    mods: list[str] = []

    def _walk(node, in_func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                _walk(child, True)                       # descend but mark: its imports are lazy/sanctioned
            elif not in_func and isinstance(child, ast.Import):
                mods.extend(a.name for a in child.names)
                _walk(child, in_func)
            elif not in_func and isinstance(child, ast.ImportFrom) and child.module:
                mods.append(child.module)
                _walk(child, in_func)
            else:
                _walk(child, in_func)                    # if_/try/with at module level stays eager
    _walk(ast.parse(py.read_text(), filename=str(py)), False)
    return mods


def _excluded(py):
    return any(ex == py or ex in py.parents for ex in EXCLUDE)


def _product_files():
    files = [ROOT / "cli" / "__init__.py"]
    for d in PRODUCT_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if not _excluded(py):
                files.append(py)
    return files


def test_product_runtime_does_not_module_import_labs():
    offenders = []
    for py in _product_files():
        for mod in _eager_imports(py):
            if any(mod == p or mod.startswith(p + ".") for p in FORBIDDEN):
                offenders.append(f"{py.relative_to(ROOT.parent)} -> {mod}")
    assert not offenders, "product module-level imports of labs (must be lazy/opt-in):\n" + "\n".join(offenders)


def test_eager_import_inside_top_level_if_is_caught(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("import os\nif True:\n    from groundloop.eval.metrics import recall_at_k\n"
                 "def f():\n    from groundloop.kb.mint import mint_playbook\n    return mint_playbook\n")
    eager = _eager_imports(p)
    assert "groundloop.eval.metrics" in eager        # eager (top-level if) -> caught
    assert "groundloop.kb.mint" not in eager          # function-local -> sanctioned, not caught
    assert "os" in eager
