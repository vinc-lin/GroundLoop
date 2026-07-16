"""Build a doc->source EntityMap from a loaded CodeWiki (module_tree) + an optional CBM join.

The module_tree-only path (cbm_client=None) needs no CBM: it maps each documented
``"relpath::Symbol"`` component to a ``file_only`` EntityEntry (we know the owning file but not
the exact node span). The optional CBM join upgrades matched entries to ``exact`` /
``qualified_suffix`` with real ``cbm_node_id`` + line spans. The CBM branch is gated/live (needs a
running CBM server) and is NOT hermetically tested; it is kept cleanly separated and defensive.
"""

from __future__ import annotations

from typing import Optional

from groundloop.engines.lore.bridge.schema import (
    CONFIDENCE,
    EntityEntry,
    EntityMap,
    ModuleMap,
)


def _split_component(comp: str) -> Optional[tuple[str, str]]:
    """``"relpath::Symbol"`` -> ``(relpath, Symbol)``; None when there is no ``"::"`` separator
    (a bare file reference with no documented symbol — the caller skips it)."""
    if "::" not in comp:
        return None
    file, _, symbol = comp.partition("::")
    file, symbol = file.strip(), symbol.strip()
    if not file or not symbol:
        return None
    return file, symbol


def _module_entries(components) -> list[EntityEntry]:
    """Map a module node's ``components`` list to file_only EntityEntries, deduped by (file, symbol)."""
    entries: list[EntityEntry] = []
    seen: set[tuple[str, str]] = set()
    for comp in components or []:
        parts = _split_component(comp)
        if parts is None:
            continue
        key = parts
        if key in seen:
            continue
        seen.add(key)
        file, symbol = parts
        entries.append(EntityEntry(
            symbol=symbol, file=file, cbm_node_id=None, lines=None,
            match_strategy="file_only", confidence=CONFIDENCE["file_only"], stale=False,
        ))
    return entries


def _walk(node_key: str, node: dict, parent_path: str, out: list[ModuleMap]) -> None:
    """Recursively turn each tree node into a ModuleMap. Child nodes carry no ``path`` field,
    so they inherit their parent's source dir."""
    path = node.get("path") or parent_path
    out.append(ModuleMap(module=node_key, wiki_page=f"{node_key}.md", path=path,
                         entries=_module_entries(node.get("components"))))
    for child_key, child in (node.get("children") or {}).items():
        _walk(child_key, child, path, out)


def apply_cbm_nodes(modules: list[ModuleMap], nodes) -> None:
    """Fill cbm_node_id/lines + raise match_strategy for entries matching a CBM NodeRecord.

    Exact = same file + same short name; qualified_suffix = same file + qualified_name ending in
    the symbol. Unmatched entries stay file_only. Pure/sync so both the library CBM branch and the
    gated CLI path share it."""
    by_file_name: dict[tuple[str, str], object] = {}
    by_file: dict[str, list] = {}
    for n in nodes:
        by_file_name[(n.file_path, n.name)] = n
        by_file.setdefault(n.file_path, []).append(n)
    for mm in modules:
        for e in mm.entries:
            node, strategy = by_file_name.get((e.file, e.symbol)), "exact"
            if node is None:
                for cand in by_file.get(e.file, []):
                    qn = cand.qualified_name or ""
                    if qn == e.symbol or qn.endswith("." + e.symbol) or qn.endswith("::" + e.symbol):
                        node, strategy = cand, "qualified_suffix"
                        break
            if node is not None:
                e.cbm_node_id = node.node_id
                e.lines = [node.start_line, node.end_line]
                e.match_strategy = strategy
                e.confidence = CONFIDENCE[strategy]


def _join_cbm(modules: list[ModuleMap], cbm_client, project: Optional[str]) -> None:
    """Gated/live: enumerate CBM nodes for every module file and apply them. Defensive — any CBM
    failure leaves the file_only entries untouched. Runs enumerate under a fresh event loop, so
    ``cbm_client`` must be a started client usable there and ``project`` its CBM project id."""
    import asyncio

    from groundloop.engines.lore.graph.nodes import enumerate_nodes_for_files

    files = sorted({e.file for mm in modules for e in mm.entries})
    if not files:
        return
    try:
        nodes = asyncio.run(enumerate_nodes_for_files(cbm_client, files, project=project))
    except Exception:  # noqa: BLE001 — CBM optional; degrade to module_tree-only, never crash
        return
    apply_cbm_nodes(modules, nodes)


def build_entity_map(wiki, repo_head, *, cbm_client=None, project=None) -> EntityMap:
    """Walk ``wiki.module_tree`` into an EntityMap. module_tree-only by default; pass a started
    ``cbm_client`` + ``project`` to additionally join CBM graph nodes (gated/live)."""
    modules: list[ModuleMap] = []
    for key, node in (getattr(wiki, "module_tree", None) or {}).items():
        _walk(key, node, "", modules)
    if cbm_client is not None:
        _join_cbm(modules, cbm_client, project)
    return EntityMap(
        built_at_repo_head=repo_head,
        wiki_commit=getattr(wiki, "wiki_commit", None),
        graph_commit=None,
        modules=modules,
    )
