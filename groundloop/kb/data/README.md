# Dev-experience KB feedstock — crash-RCA playbook corpus

`aaos_kb_seed.toml` is the **content** side of the SP3 dev-experience KB: a small, grounded, leak-safe
corpus of AAOS log-analysis + bug-fixing playbooks ("Skills"). It is **data**, decoupled from the SP3
registry/arm code (`groundloop/skills/`, currently on the `worktree-sp3-kb-arm` branch) — the corpus is
the shared interface the arm consumes, exactly as the synth-log dataset is the interface the matcher
consumes.

## Format (SP3 `Skill` contract)
Each `[[skill]]` has: `id`, `provenance`, `signals` (retrieval tags), `hint_apis` (generic API/symbol
names a correct fix references), `guidance`, and a `[skill.match]` **declarative** predicate (no code in
data). Predicate keys are a **closed vocabulary** (`any_text`, `any_text_regex`, `any_errors`,
`any_methods`, `any_{family}[_regex]`, …); `always`/`repo_in` are forbidden here (a repo-pinned Skill is
a lookup-table row / overfit). `guidance` is **localization-first**, structured as three clauses because
the Skill is injected at BOTH the localize and fix stages:

- **Signature:** what the log/ticket looks like (the crash fingerprint).
- **Localize:** where the owning code for this signature *generically* lives (helps rank candidate files
  → earns `file_recall`). Never a concrete path or repo.
- **Fix:** typical root cause + the corrective change + which API/symbol a correct patch references.

## Hard rule — leak safety (grounding over narrative)
Every playbook is **generic to the crash signature** and names **no fleet repo or owner token**
(namespaces/slugs/sonames). Enforced by `groundloop/kb/validate.py` (`validate_corpus`), whose denylist
is sourced from the authoritative `FLEET_OWNER_TOKENS`; `KEEP` dependency tokens (`android.`,
`androidx.`, `SurfaceTexture`, `libaaudio.so`, …) are **not** leaks. `tests/kb/test_feedstock.py` gates
this on every change, and (post-SP3-merge, via `importorskip`) loads the corpus through the real registry.

## Composition with the SP3 seed
This corpus **extends, does not replace**, the SP3 placeholder seed
(`adapters/skills/data/aaos_playbooks.toml`, 4 native/ops playbooks). The signatures are **disjoint**
(SP3 seed = native lib-load / JNI-handle + CBM/produce ops; here = SEGV / heap-abort / lifecycle / media
/ concurrency), so the merged registry can load both. The merge point (one file vs. two) is a
coordination item for the SP3 session — see the design spec.

## Grounding evidence (does it fire on real cases?)
Predicate firing over the eval datasets (via the real `AndroidSignalExtractor` + a mirror of
`compile_predicate`), 2026-07-06:

- **`dataset-synth` (212 signal-rich synth logs): 55% coverage** (117/212 fire ≥1 Skill) — dominated by
  `native-null-deref-segv` (74; every synth native backtrace carries the SIGSEGV template) and
  `fragment-view-after-destroy-npe` (40; Java NPE cases).
- **`dataset-full` (261 real mined logs): 7% coverage** — real prose/framework logs lack signal (the same
  reason Stage-1 recall@1 is ~0.02 on real logs vs 0.60 on synth).
- **3 Skills fire on 0 synth cases** (`binder-transaction-too-large`, `illegalstate-after-savedinstancestate`,
  `main-thread-blocking-anr`) — a **dataset gap, not a corpus gap**: we don't synthesize those crash
  classes yet. A signal to broaden the synth generator.

## Status + provenance discipline
These Skills are **`candidate` tier**: authored (cold-start), leak-safe, and grounded to fire on real
cases — but with **no measured effectiveness yet**. "Validated" requires the SP3 measured arm + the
two-sided fix-eval A/B (`Δpatch_applies`/`Δrequired_api`/`Δresolved` with **no** `Δfabrication_rate`
regression), on a **held-out / temporal split** so lift means lift-on-unseen.

`provenance` today names each Skill's real basis. The eventual per-entry provenance sidecar (for the
lifecycle/tiering) records: source lineage, the `validating_case_ids` (split-tagged), the `measured_lift`
(flagged **proxy**), and the `evidence_context` (atlas SHA + `bge-m3` + model pin + date) the lift was
measured against — so a stale entry is auto-demotable and every claim is traceable. See the design spec.
