# GroundLoop — Type-2 live eval environment setup

Stand up the live evaluation substrate: a real `atlas.db` over the pinned corpora, so `AtlasIndex`
matches tickets to repos over real code (and the gated live tests run). Type-1 hermetic tests need
none of this; see `groundloop-testing-strategy.md` for the two-surface split.

## Prerequisites (this machine — verified 2026-07-04)
- **CBM**: `codebase-memory-mcp 0.8.1` installed in `.venv` — ✅ runs.
- **produce LLM**: `deepseek-chat` via the LiteLLM gateway — ✅ up (HTTP 200).
- **bge-m3 embeddings**: on the same gateway but GPU/Ollama-backed — **must be up** (see gate below).
- **corpora**: `/mnt/x/code/corpora/` at pinned SHAs (`corpus.toml`); registry `corpora/atlas.toml`.

## Config
Copy `.env.example` → `.env` (gitignored) and fill it, or use the provided `.env` which reuses the
gateway creds from `loop-agent/.env`. Source it before every `gloop` call:
```
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a
```
Key vars: `KLOOP_EMBED_{BASE_URL,API_KEY,MODEL=bge-m3}`, `KLOOP_ATLAS_DB`, `KLOOP_REGISTRY`,
`KLOOP_PRODUCE_{BASE_URL,API_KEY,MAIN_MODEL,...,READY=1}`, `KLOOP_CBM_READY=1`.

## Embedding-host gate
The build's embed step needs the bge-m3 backend. Check it is healthy (prints `200` when up, `000`
while the GPU/Ollama host is down):
```
set -a; . ./.env; set +a
curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 "${KLOOP_EMBED_BASE_URL%/}/embeddings" \
  -H "Authorization: Bearer $KLOOP_EMBED_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","input":"hi"}'
```

## Build (once the gate reads 200)
```
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a
mkdir -p "$HOME/.groundloop"

# 1. wikis (doc units) — host-independent, can run before the embed host is up:
.venv/bin/gloop produce --repo /mnt/x/code/corpora/android-gpuimage-plus \
                        --out  /mnt/x/code/corpora/_wiki/android-gpuimage-plus

# 2. build atlas.db = wiki doc units + CBM symbol units + bge-m3 vectors:
.venv/bin/gloop index --registry /mnt/x/code/corpora/atlas.toml

# 3. verify:
.venv/bin/gloop doctor        # repos > 0, units > 0, embed gateway OK, CBM OK
```

## Flip the gated live tests
The two `skipif`-gated tests run once the services are declared ready:
```
set -a; . ./.env; set +a
KLOOP_EMBED_API_KEY="$KLOOP_EMBED_API_KEY" KLOOP_CBM_READY=1 KLOOP_PRODUCE_READY=1 \
  .venv/bin/python -m pytest tests/e2e/ -q
```
`tests/e2e/test_index_build_live.py` is the M1 milestone acceptance (produce + CBM + embed →
atlas.db with both doc and symbol units; AtlasIndex retrieves a known symbol).

## Growing the fleet
Uncomment `libxcam` / `ndk-samples` in `corpora/atlas.toml` and re-run produce + index for each. A
meaningful Stage-1 match needs several confusable repos so a 1/N guess scores far below a real match.
