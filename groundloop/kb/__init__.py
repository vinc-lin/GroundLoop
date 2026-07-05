"""GroundLoop dev-experience KB feedstock (SP3 support, dataset/eval lane).

This package owns the *content* side of the Skill KB: the authored, leak-safe, grounded playbook
corpus (`data/*.toml`) plus a validator/loader that mirrors the SP3 `Skill` TOML contract so the
corpus is authorable and regression-checkable on master BEFORE the SP3 registry code merges. It is
deliberately decoupled from `groundloop/skills/` (the SP3 registry/arm, in the worktree-sp3-kb-arm
branch) — the corpus is the shared interface the arm consumes, exactly as the synth-log dataset is
the shared interface the matcher consumes.
"""
