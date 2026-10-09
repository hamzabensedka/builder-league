# Submission Notes — DOO Builders League (C1–C8)

One repo, one modular monolith, eight challenges. Each challenge is a "core"
(`core/<name>core/`) with a UI tab on the live inspector and a 90-second demo
script. Every enforcement path is deterministic (crypto + policy); LLMs are
propose-only and optional.

- **Repo:** https://github.com/hamzabensedka/builder-league (clean clone runs — see README)
- **Live demo:** https://builder-league-trust.onrender.com (free tier: first request after idle takes ~30–60s to wake; `/health` answers `{"status":"ok"}`)
- **Full suite:** 443 tests green; `ruff` clean; `lint-imports` contracts kept
- **Live verification:** `node scripts/smoke-all.mjs` boots the real server and drives 48 HTTP checks across all 8 demo flows (8/8 challenges OK)

## Rubric → evidence map

| Challenge | Tab | Core mechanic (demo) | Failure test | Architecture / thesis | 90s script |
|---|---|---|---|---|---|
| C1 The Agent That Earns Trust | C1 · Trust | accept → issue → forgery refused → scope escape refused → revocation sticks, each receipted (`llm_called: false`) | SpooferBot: forged Acme grant, no authority, scope escape, revoked grant — all refused | [docs/architecture.md](docs/architecture.md) · [docs/thesis.md](docs/thesis.md) | [demo/script.md](demo/script.md) · `demo/run_demo.py` |
| C2 The Decision Engine | C2 · Decision Engine | execute ($120 refund) · ask ($2400, names missing `invoice_id`) · escalate ($8000 irreversible deploy) — five weighted signals rendered | $8000 deploy with full authority but missing `change_ticket`: never executes, names the gap | [docs/architecture-c2.md](docs/architecture-c2.md) · [docs/thesis-c2.md](docs/thesis-c2.md) | [demo/script-c2.md](demo/script-c2.md) |
| C3 The Adaptive Agent | C3 · Adaptive Agent | plan → execute → observe → re-plan on contradiction, with "I changed my mind because…" trace + plan diff; non-adaptive baseline runs the same world blind | flapping price → A→B→A oscillation detected, damping escalates to human, frozen | [docs/architecture-c3.md](docs/architecture-c3.md) · [docs/thesis-c3.md](docs/thesis-c3.md) | [demo/script-c3.md](demo/script-c3.md) |
| C4 Memory That Knows It Might Be Wrong | C4 · Memory | "I might be wrong" verdict on a weak inference (40% < threshold, gaps named); user correction supersedes; TTL sweep; signed Ed25519 revocation tombstones | contradictory facts + stale TTL + privacy revocation — all explicit, receipted | [docs/architecture-c4.md](docs/architecture-c4.md) · [docs/thesis-c4.md](docs/thesis-c4.md) | [demo/script-c4.md](demo/script-c4.md) |
| C5 The Agent Control Tower | C5 · Control Tower | fleet live over SSE; risky deploy parks in approval queue; operator deny/approve; replay; exportable audit | rogue objective injected → refusal streak → drift flag → auto-pause → replay → kill (terminal), full incident in audit export | [docs/architecture-c5.md](docs/architecture-c5.md) · [docs/thesis-c5.md](docs/thesis-c5.md) | [demo/script-c5.md](demo/script-c5.md) |
| C6 The Autonomous Company Simulator | C6 · Company | four roles share one event spine; run a day → KPIs move; human inbox escalation; replay scrubber re-folds any day | ⚡ cash crunch → self-corrects with zero human input; ☠ rogue sales → TrustCore refuses → role paused, others hold the line | [docs/architecture-c6.md](docs/architecture-c6.md) · [docs/thesis-c6.md](docs/thesis-c6.md) | [demo/script-c6.md](demo/script-c6.md) |
| C7 Beyond the Chatbot | C7 · Canvas | ambient canvas renders nothing by default; the interface itself initiates one decision card (evidence chain, pre-simulated diff, rollback preview); "⇄ What this replaces" toggle shows the same fleet as a C5 dashboard | reject a card → receipted MemoryCore correction demotes that intent kind; second rejection degrades gracefully to raw evidence (manual mode) | [docs/architecture-c7.md](docs/architecture-c7.md) · [docs/thesis-c7.md](docs/thesis-c7.md) | [demo/script-c7.md](demo/script-c7.md) |
| C8 Simulate Before You Act | C8 · Simulate first | approval screen IS the computed before/after diff (no confirm dialog); rollback path pre-computed; approve → real write | concurrent $200 hold injected between simulate and approve → post-execution invariant check catches 900+200 > 1000 → escalated, compensating rollback restores | [docs/architecture-c8.md](docs/architecture-c8.md) · [docs/thesis-c8.md](docs/thesis-c8.md) | [demo/script-c8.md](demo/script-c8.md) |

## Key decisions (for the notes field)

- **No LLM on any enforcement path** — enforced by import-linter contracts; every receipt carries `llm_called: false`. LLMs (OpenRouter free tier) are propose-only narrators with scripted fallback; clean clones run fully offline.
- **No aggregate reputation score** (C1 disqualifier avoided): every count traces to an individually verifiable signed claim.
- **Hexagonal architecture**: pure domains → application services (ports as Protocols) → in-memory adapters → FastAPI. Durable storage is a swap behind the ports, deliberately deferred.
- **Honest limits disclosed** per challenge in the README ("this breaks when…"): in-memory stores reset on redeploy, keyword (not semantic) retrieval in C4, deterministic role policies in C6 with the LLM as propose-only ChiefOfStaff, threshold gaming noted in C2.

## AI usage

Built with an AI pair-programmer (Cursor). Architecture, security rules, and
plans were reviewed and approved by the human submitter before code; AI wrote
implementation against failing tests (TDD) under a gates ledger
(`gate-check.mjs`-style acceptance checks).

## Out of scope

No DID resolution / blockchain anchoring (VC-*shaped*, not full SSI); no
multi-tenant auth on the inspector UI (demo surface, enforcement lives in the
cores); no durable persistence by default (ports isolate the swap).
