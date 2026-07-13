# Labs arms + the `KLOOP_LABS` profile — design (2026-07-13)

**Status:** design, 2026-07-13. Approved decision (this session): **"Selectable arms + `KLOOP_LABS` switch"** —
wire every experimental Candidate capability into `gloop run` as a *selectable* arm, plus one
`KLOOP_LABS=1` / `--profile labs` that flips the run **defaults** to the experimental stack for a
production-test deployment, while real production (profile unset) stays Core. The rejected alternative was a
global default-flip (incoherent for competing matchers + re-opens the incorrect-run risk).

## Goal

Make the proxy-validated but production-unread Candidates **runnable and gradeable from `gloop run` in
production**, so each can earn its `[production]` read — **without** changing the Core default for real
production runs. Two levers:
1. **Selectable arms** — new `--match-arm` choices (`functional`, `dispatch`, `semantic`, `judge`) + a new
   `--localize {atlas,semantic}`, each wired at the composition root exactly like their `gloop eval`/`funceval`
   construction, with fail-closed/honest-fallback guards for their creds/artifacts.
2. **A per-environment profile switch** — `KLOOP_LABS=1` (env) or `--profile labs` sets the *defaults* to the
   experimental stack; explicit flags always override; the actually-run arm is recorded honestly.

**Non-goal / preserved invariant:** with the profile unset, **every default is unchanged** (match `component`,
localize `atlas`, fix `plan`). No Candidate becomes a silent default. This is the exact analogue of the
`KLOOP_DEV` dev-gate: a deliberate, per-environment mode switch, recorded in the run manifest. **Never edit
`core/`; never touch the SQLite schema.**

## What's being wired (grounded in the real constructors)

| Arm (`--match-arm`) | Index (ctor) | Paired extractor | Needs beyond the atlas |
|---|---|---|---|
| `functional` | `FunctionalTextIndex(profile_db, embedder, atlas_db)` | `FunctionalTextExtractor` | embedder (`KLOOP_EMBED_*`) **+ a repo-text profile artifact** |
| `dispatch` | `DispatchIndex(fault_index, functional_index, fault_scale)` | `DispatchExtractor` | everything `functional` needs (it composes `FaultRoutingIndex` + `FunctionalTextIndex`) |
| `semantic` | `SemanticAtlasIndex(db_path, embedder)` | `AndroidSignalExtractor` (base) | embedder (`KLOOP_EMBED_*`) |
| `judge` | `LLMJudgeIndex(AtlasIndex(db), GatewayJudge(...))` | `AndroidSignalExtractor` (base) | judge model creds |
| `routing` *(already wired)* | `FaultRoutingIndex(db)` | `FaultSignalExtractor` | atlas only |

`--localize semantic` → `SemanticAtlasIndex(db, embedder).retrieve` (embedder needed).

## Design

### A. Selectable match arms (composition root, `cli/__init__.py`)

Extend `--match-arm` choices to `flood|routing|component|functional|dispatch|semantic|judge`. In the run
handler's index-selection block (which already swaps index+extractor per arm), add a branch per new arm that
mirrors the eval/funceval construction (`GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)`
when creds are present; `GatewayJudge(...)` for judge). Each new arm swaps in its paired extractor, exactly as
`routing`→`FaultSignalExtractor` and `component`→`ComponentExtractor` do today. The **honest `match_arm`
recording** convention already in place is preserved: if an arm degrades (missing creds/artifact), the
run-record/manifest records the arm that *actually* ran, never the requested one.

### B. Selectable localize + the `SplitIndex` composite

`run_ticket` (frozen) calls **one** `index` object for both `rank_repos` and `retrieve`. Today localize
inherits the match index's `retrieve` (FTS5 for flood/component/routing; vector for semantic). To choose
localize **independently** of match, add `--localize {atlas,semantic}` (default `atlas`) and a tiny
composition-root adapter:

```python
class SplitIndex:                       # CodeIndex: rank_repos from `match`, retrieve from `localize`
    def __init__(self, match, localize):
        self._m, self._l = match, localize
    def rank_repos(self, signals, catalog): return self._m.rank_repos(signals, catalog)
    def retrieve(self, repo, query):        return self._l.retrieve(repo, query)
```

Wire it only when the requested `--localize` differs from the match index's native retrieve (e.g. match
`component` + localize `semantic` → `SplitIndex(ComponentPriorIndex(...), SemanticAtlasIndex(...))`); otherwise
pass the single index unchanged (zero overhead for the common path). `--localize semantic` needs the embedder;
absent → fail-closed or honest-fallback per §D.

### C. The `KLOOP_LABS` / `--profile` switch

Add `--profile {core,labs}` (default `core`) to the run parser; `KLOOP_LABS=1` is the env equivalent
(`profile = "labs" if args.profile == "labs" or KLOOP_LABS else "core"`). When `labs` **and the flag was not
given explicitly**, the defaults change:
- match default `component` → **`routing`** (the one experimental arm needing *no* extra creds/artifact — atlas
  only — and the strongest proxy, 0.94);
- localize default `atlas` → **`semantic`** (honest-fallback to `atlas` + a loud warning if no embedder);
- fixer stays `plan` (already the default).

**Precedence:** an explicit `--match-arm` / `--localize` / `--fixer` always wins over the profile (argparse
default-sentinel check: only apply the labs default when the user left the flag at its default). So
`--profile labs --match-arm functional` runs functional; bare `--profile labs` runs the routing+semantic+plan
stack. This gives one-command experimental runs *and* per-arm control.

### D. Fail-closed / honest-fallback guards (per arm)

Consistent with the existing `component`→flood and `--fixer model` guards:
- **`semantic` / `judge` / `functional` / `dispatch`** require gateway/judge creds (and functional/dispatch a
  repo-text **profile artifact**, `--functional-profile` / `KLOOP_FUNCTIONAL_PROFILE`, built offline like the
  affinity table). Missing a **hard** dependency → **fail-closed** (`exit 2`, clear message) when the arm was
  requested **explicitly** (the operator asked for it; don't silently degrade). Under the **labs profile
  default** (arm not explicitly requested), a missing dependency **degrades loudly** to the next-best real arm
  (semantic→atlas localize; routing→flood match if even the atlas arm can't build) and records the arm that
  ran — same "honest degrade, never silent" rule as `component`.
- `functional`/`dispatch` without the profile artifact: fail-closed if explicit, honest-degrade if labs-default.

### E. Honest recording

The run-record already stores the actual `match_arm`. Extend the per-batch `manifest.json` (`run/manifest.py`)
with `profile` (`core`/`labs`) and `localize` (`atlas`/`semantic`), so a `[production]`-tagged card is
unambiguous about which experimental stack produced it. `grade-run`/`--compare` need no change (they read the
card + run-records).

### F. Governance (capabilities.md + workflows.md)

- The experimental arms stay **Candidate** — they are now *run-reachable* (opt-in via `--match-arm`/`--localize`
  or the labs profile) but **not** the Core default. Their `capabilities.md` / feature-map **Blocker → Core**
  moves from **"wire into run + `[production]`"** to just **"a `[production]` read"** (the wiring is done).
- **`KLOOP_LABS` / `--profile labs`** is registered as a new **Core** per-environment switch (like the
  `KLOOP_DEV` dev-gate): it changes defaults only where explicitly enabled; real production (unset) is
  Core-identical. `SplitIndex` = Core (a composition-root adapter).
- §4 enforcement note: the CI/regression assertion "production defaults are Core-aligned" must check defaults
  **with `KLOOP_LABS` unset** (labs is an opt-in test mode, not the production default).

## Data flow (a labs production-test run)

`KLOOP_LABS=1 gloop run --index-db <atlas> --repos <snaps> --out o` → profile=`labs` → defaults become
`routing` match + `semantic` localize (or honest fallback) + `plan` fix → `run_ticket` → run-records
(`match_arm=routing`) + `manifest.json` (`profile=labs, localize=semantic`) → `gloop grade-run … --compare
<prev>` → a `[production]`-tagged read of the experimental stack, per arm.

## Testing (hermetic, Type-1)

- **Arm construction:** each new `--match-arm` builds the right index+extractor with a stub/canned embedder &
  judge (monkeypatched), over a fixture atlas — a composition-root test per arm (no live gateway).
- **`SplitIndex`:** `rank_repos` comes from `match`, `retrieve` from `localize` (a 2-double test).
- **Profile switch:** `--profile labs` (and `KLOOP_LABS=1`) flips the defaults to routing+semantic+plan; an
  explicit `--match-arm`/`--localize`/`--fixer` overrides the profile; bare `core` is unchanged.
- **Guards:** an explicitly-requested `semantic`/`judge`/`functional` arm without creds/profile → `exit 2`;
  the same arm under labs-default degrades loudly and records the fallback arm.
- **Manifest:** records `profile` + `localize`.
- **Governance regression:** with `KLOOP_LABS` unset the run defaults are still `component`/`atlas`/`plan`.

## Non-goals

Changing the real-production default (labs is opt-in per environment); promoting any arm to Core (that still
needs a `[production]` read); building the repo-text **profile** or affinity **artifacts** (offline build
steps, already exist / out of scope here); a fusion matcher that runs several arms at once; any `core/` or
schema edit.

## Risks

- **Creds/artifacts sprawl** — four arms each need embedder/judge creds and (functional/dispatch) a profile
  artifact. Mitigated by fail-closed-when-explicit + honest-degrade-under-labs, and by making `routing` (atlas
  only) the labs default so a bare labs run works with zero extra config.
- **`dispatch` is the most complex** (composes fault + functional). Mitigated: build it from the already-wired
  `FaultRoutingIndex` + the new `functional` construction; if its profile artifact is absent it fails-closed
  (explicit) / degrades (labs) like the others.
- **Labs profile mistaken for production** — mitigated by recording `profile=labs` in the manifest and the
  §F CI check that production defaults are asserted with `KLOOP_LABS` unset.
- **Judge has no logged efficacy** — it is wired for completeness but the weakest; its `[production]` read may
  simply confirm it isn't worth Core. That is a valid outcome of making it runnable.
