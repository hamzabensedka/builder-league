# C7 Architecture — AmbientCore: data → intent inference → surfaced decision → action

AmbientCore replaces the dashboard + chatbot for one real workflow: **an ops
operator on shift** watching a fleet of agents move real money. It composes
the five existing cores through their public application surfaces only; it
adds no new enforcement, it changes *how decisions reach a human*.

## The pipeline

```
TowerCore event stream ─┐
fleet state (registry)  ├─► INTENT FOLD (pure, deterministic)
SimCore ledger          │      candidate hypotheses: kind, confidence,
MemoryCore corrections ─┘      evidence[], missing[], proposed_action
                                        │
                                        ▼
                                RANKER (pure, deterministic)
                                argmax above SURFACE_THRESHOLD (0.55);
                                kinds with 2+ corrections are EXHAUSTED
                                → manual fallback, never a third wrong card
                                        │
                                        ▼
                            DECISION CARD (at most ONE on screen)
                            rationale (narrator, propose-only LLM or scripted)
                            + evidence chain
                            + PRE-SIMULATED before/after diff (SimCore fork)
                            + rollback preview
                                        │
                    approve / edit / reject  (receipted REST verbs)
                                        │
                                        ▼
                        EXECUTION THROUGH THE REAL CORES
                        parked-approval cards resolve the tower queue;
                        purchases execute the pre-computed SimCore sim;
                        containment cards drive the InterventionGate.
                                        │
                        reject → MemoryCore correction fact (signed-worthy,
                        receipted, decaying) → DEMOTES that intent kind on
                        the next fold. The wrong-guess recovery lives in the
                        fold itself.
```

## Layers (import-linter enforced, contracts 32–36)

- **domain** (`fold.py`, `rank.py`, `card.py`, `intents.py`) — pure. No I/O,
  no frameworks, no LLM, no httpx. Fail-closed constructors; deterministic
  fold; immutable card lifecycle (`surfaced → approved|edited|rejected|manual`).
- **application** (`ports.py`, `services.py`) — the inference loop. Reaches
  Tower/Trust/Decision/Sim/Memory only through application+domain surfaces.
- **adapters** (`memory.py`, `llm.py`) — in-memory card store, manual clock,
  scripted narrator, and the OpenRouter narrator. The narrator is the ONLY
  LLM seam: propose-only, single line, parsed by `parse_rationale` (choke
  point: one line, ≤300 chars, never raises). Any failure → scripted
  fallback; clean clones run fully offline.

## Why this is "real intent inference, not hardcoded flows"

Cards emerge from **event shapes**: a parked approval, a drift flag, a
low-stock observation, a ledger near its limit. The demo script only seeds a
world; it never names a card. Every score is a named constant
(`W_DRIFT_FLAG = 0.85`, `SURFACE_THRESHOLD = 0.55`, `DEMOTION_FACTOR = 0.5`),
every surfaced card carries its evidence chain, and `/api/ambient/intents`
exposes the runner-ups the interface chose NOT to show — the restraint is
inspectable.

## The dogfood contrast

C5 shipped a *dashboard* for this exact fleet. C7 renders the SAME fleet as
an ambient canvas: `/api/tower/fleet` (the old interface) and
`/api/ambient/canvas` (the new one) read the same stream. The UI's
"⇄ What this replaces" button toggles between them on live data — the
side-by-side is not a mockup.
