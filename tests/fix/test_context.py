"""Grounded code-understanding fix context: render_codewiki / render_cbm / FixContextProvider.

CodeWiki context is GROUNDED — only real atlas `doc`-unit text, resolved file->module through the
entity_map, reaches the block. CBM context is GROUNDED — only real `snippet` / `call_neighbors` output.
Every path is fail-safe: a missing store / map / cbm, or empty inputs, yields "" so the fix preamble
concatenates cleanly (byte-identical to no injection)."""
from groundloop.core.types import Signals
from groundloop.engines.lore.bridge.schema import EntityEntry, EntityMap, ModuleMap
from groundloop.engines.atlas.store import Store, Unit
from groundloop.fix.context import (FixContextProvider, _symbols_for, render_cbm, render_codewiki)

_SRC = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


# ---- render_codewiki -------------------------------------------------------------------------------

class _DocProvider:
    def __init__(self, docs):
        self._docs = docs

    def module_doc(self, file):
        return self._docs.get(file, "")


def test_render_codewiki_empty_when_no_provider():
    assert render_codewiki([_SRC], provider=None) == ""


def test_render_codewiki_empty_when_nothing_resolves():
    assert render_codewiki([_SRC], provider=_DocProvider({})) == ""


def test_render_codewiki_block_shape_and_grounded_text():
    out = render_codewiki([_SRC], provider=_DocProvider({_SRC: "Native image handler module."}))
    assert out.startswith("\n\n# CodeWiki module summaries\n")
    assert f"## {_SRC}" in out
    assert "Native image handler module." in out


def test_render_codewiki_dedupes_same_module_doc():
    prov = _DocProvider({"a.cpp": "same module doc", "b.cpp": "same module doc"})
    out = render_codewiki(["a.cpp", "b.cpp"], provider=prov)
    assert out.count("same module doc") == 1     # two files, one module -> one block


def test_render_codewiki_bounds_length():
    out = render_codewiki([_SRC], provider=_DocProvider({_SRC: "x" * 5000}), max_chars=100)
    assert out.count("x") == 100


# ---- render_cbm ------------------------------------------------------------------------------------

class _StubCBM:
    def __init__(self, snippets=None, neighbors=None):
        self._s = snippets or {}
        self._n = neighbors or {}

    def snippet(self, qn):
        return self._s.get(qn, "")

    def call_neighbors(self, qn):
        return self._n.get(qn, [])


def test_render_cbm_empty_when_no_cbm():
    assert render_cbm(["onBind"], cbm=None) == ""


def test_render_cbm_empty_when_symbol_unresolved():
    assert render_cbm(["ghost"], cbm=_StubCBM()) == ""


def test_render_cbm_block_has_source_and_calls():
    cbm = _StubCBM(snippets={"onBind": "void onBind(){}"},
                   neighbors={"onBind": ["Caller.a", "Callee.b"]})
    out = render_cbm(["onBind"], cbm=cbm)
    assert out.startswith("\n\n# Live code-graph context (CBM)\n")
    assert "## onBind" in out
    assert "source:\nvoid onBind(){}" in out
    assert "calls: Caller.a, Callee.b" in out


def test_render_cbm_failsafe_on_error():
    class _Boom:
        def snippet(self, qn):
            raise RuntimeError("down")

        def call_neighbors(self, qn):
            raise RuntimeError("down")
    assert render_cbm(["onBind"], cbm=_Boom()) == ""


def test_render_cbm_caps_symbols():
    cbm = _StubCBM(snippets={f"s{i}": f"src{i}" for i in range(10)})
    out = render_cbm([f"s{i}" for i in range(10)], cbm=cbm, max_symbols=2)
    assert out.count("## s") == 2


def test_symbols_for_orders_and_dedupes():
    sig = Signals(classes=("Foo",), methods=("onBind", "Foo"), symbols=("nativeInit",))
    # methods first, then symbols, then classes; "Foo" appears once (dedup)
    assert _symbols_for(sig) == ["onBind", "Foo", "nativeInit"]


def test_symbols_for_none():
    assert _symbols_for(None) == []


# ---- FixContextProvider (real store + entity_map) --------------------------------------------------

def _entity_map():
    return EntityMap(
        built_at_repo_head="h", wiki_commit=None, graph_commit=None,
        modules=[ModuleMap(module="MyModule", wiki_page="MyModule.md", path="p",
                           entries=[EntityEntry(symbol="foo", file=_SRC, cbm_node_id=None,
                                                lines=None, match_strategy="exact", confidence=1.0)])])


def _store_with_doc(db_path):
    s = Store(db_path)
    units = [
        Unit(repo="r", kind="doc", name="Overview", qualified_name=None, file="MyModule.md",
             repo_head="h", text="Overview\nLoads native image handlers.", meta={"module": "MyModule", "ord": 0}),
        Unit(repo="r", kind="doc", name="Details", qualified_name=None, file="MyModule.md",
             repo_head="h", text="Details\nHandler lifecycle.", meta={"module": "MyModule", "ord": 1}),
    ]
    s.reindex_repo("r", list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return s


def test_provider_module_doc_resolves_file_to_module_to_doc(tmp_path):
    prov = FixContextProvider(store=_store_with_doc(str(tmp_path / "a.db")), entity_map=_entity_map())
    doc = prov.module_doc("r", _SRC)
    assert "Loads native image handlers." in doc
    assert "Handler lifecycle." in doc            # both chunks, in ord order


def test_provider_module_doc_empty_for_unmapped_file(tmp_path):
    prov = FixContextProvider(store=_store_with_doc(str(tmp_path / "b.db")), entity_map=_entity_map())
    assert prov.module_doc("r", "src/unknown.cpp") == ""


def test_provider_module_doc_empty_without_store():
    assert FixContextProvider(store=None, entity_map=_entity_map()).module_doc("r", _SRC) == ""


def test_provider_module_doc_empty_without_map(tmp_path):
    prov = FixContextProvider(store=_store_with_doc(str(tmp_path / "c.db")), entity_map=None)
    assert prov.module_doc("r", _SRC) == ""


def test_provider_preambles_compose_codewiki_and_cbm(tmp_path):
    cbm = _StubCBM(snippets={"onBind": "void onBind(){}"}, neighbors={"onBind": ["Callee.b"]})
    prov = FixContextProvider(store=_store_with_doc(str(tmp_path / "d.db")), entity_map=_entity_map(),
                              cbm=cbm)
    cw, cbm_pre = prov.preambles("r", [_SRC], Signals(methods=("onBind",)))
    assert "# CodeWiki module summaries" in cw and "Loads native image handlers." in cw
    assert "# Live code-graph context (CBM)" in cbm_pre and "void onBind(){}" in cbm_pre


def test_provider_entity_map_and_cbm_may_be_callables(tmp_path):
    store = _store_with_doc(str(tmp_path / "e.db"))
    em = _entity_map()
    cbm = _StubCBM(snippets={"onBind": "src"})
    prov = FixContextProvider(store=store, entity_map=lambda repo: em if repo == "r" else None,
                              cbm=lambda repo: cbm if repo == "r" else None)
    cw, cbm_pre = prov.preambles("r", [_SRC], Signals(methods=("onBind",)))
    assert "Loads native image handlers." in cw and "src" in cbm_pre
    # a repo the callables don't know about -> both empty (fail-safe)
    cw2, cbm2 = prov.preambles("other", [_SRC], Signals(methods=("onBind",)))
    assert cw2 == "" and cbm2 == ""
