"""CI guard: the product runtime must not import the produce doc-generator at module level.
Produce is a build-time-only tool (reached via the lazy import inside cli._run_produce)."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "groundloop"
PRODUCT_DIRS = ["core", "adapters", "domains", "run"]
FORBIDDEN_PREFIX = "groundloop.engines.produce"


def _module_level_imports(py: pathlib.Path):
    tree = ast.parse(py.read_text(), filename=str(py))
    for node in tree.body:                                    # top-level only — function-local imports excluded
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _product_files():
    files = [ROOT / "cli" / "__init__.py"]
    for d in PRODUCT_DIRS:
        files += (ROOT / d).rglob("*.py")
    return files


def test_product_does_not_module_import_produce():
    offenders = []
    for py in _product_files():
        for mod in _module_level_imports(py):
            if mod.startswith(FORBIDDEN_PREFIX):
                offenders.append(f"{py.relative_to(ROOT.parent)} -> {mod}")
    assert not offenders, "product module-level imports of produce (must be lazy/build-only):\n" + "\n".join(offenders)
