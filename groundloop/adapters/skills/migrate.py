"""Author-facing migration transform: foreign markdown+front-matter Skills (the shape the real dev-
experience Skills arrive in post-migration) -> groundloop Skill records. The predicate lives in a FOREIGN
trigger vocabulary (`triggers:`) that triggers_to_spec translates into the same declarative match spec the
native seed carries; compile_predicate then builds the closure. See docs/skill-kb-migration.md."""
from __future__ import annotations

from pathlib import Path

from groundloop.skills.base import Skill
from groundloop.skills.predicate import compile_predicate

# The documented trigger vocabulary -> declarative match-spec fragments. Real migrations extend this map.
_TRIGGER_MAP: dict[str, dict] = {
    "native-crash": {"any_text": ["unsatisfiedlinkerror", "no implementation found", "native method"]},
    "so-load-failure": {"any_text": ["couldn't find", "load library"], "any_text_regex": [r"lib\w+\.so"]},
    "jni-handle": {"any_text": ["nativecreatehandler", "registernatives", "nativecreate", "nativerelease"]},
}


def triggers_to_spec(triggers: list[str]) -> dict:
    """Merge foreign trigger names into one declarative match spec (union per key, de-duped, ordered)."""
    spec: dict[str, list] = {}
    for t in triggers:
        frag = _TRIGGER_MAP[t.strip()]              # KeyError on an undocumented trigger (fail loud)
        for k, vals in frag.items():
            bucket = spec.setdefault(k, [])
            bucket.extend(v for v in vals if v not in bucket)
    return spec


def _parse_front_matter(md: str) -> tuple[dict, str]:
    """Split a `--- ... ---` front-matter block (scalars + comma-lists) from the guidance body."""
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("markdown skill needs a --- front-matter block")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    meta: dict = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    body = "\n".join(lines[end + 1:]).strip()
    return meta, body


def migrate_markdown_skills(dir_path: str) -> list[Skill]:
    out: list[Skill] = []
    for p in sorted(Path(dir_path).glob("*.md")):
        meta, body = _parse_front_matter(p.read_text())
        triggers = [t for t in meta.get("triggers", "").split(",") if t.strip()]
        out.append(Skill(
            id=meta["id"],
            applies_to=compile_predicate(triggers_to_spec(triggers)),
            guidance=body,
            signals=tuple(t.strip() for t in triggers),
            provenance=meta.get("provenance", f"md:{p.name}"),
        ))
    return out
