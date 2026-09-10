# 90-second demo runbook — The Agent That Earns Trust

Prereqs: API running (`uvicorn api.main:create_app --factory --port 8000`),
inspector UI open (`cd ui && npm run dev` → localhost:5173), and a second
terminal for `demo/run_demo.py`. Narrate over the UI; the script prints the
same receipts in the terminal as backup.

| Time | Beat | Say / show |
|------|------|-----------|
| 0:00–0:10 | Setup | "Two independent agents plus an attacker, each with their own Ed25519 keypair. No scores anywhere — only signed claims." Show empty inspector. |
| 0:10–0:25 | Accept | Run script beats 1. UI: BuyerBot profile shows 1 authority grant + 2 completion vouches, each expandable to raw signed JSON with ✓ verified. Receipt: **ALLOW**, `llm_called=false`. "Enforcement is crypto + policy, not a model." |
| 0:25–0:40 | Credential issued | Beat 2: VendorBot signs a TaskCompletion; BuyerBot's completion count ticks 2 → 3 live in the UI. "Trust accrues as signed claims from counterparties." |
| 0:40–0:55 | Forgery refused | Beat 3: SpooferBot forges an Acme grant, signed with its own key. Terminal: HTTP 400 `credential signature does not verify`. "The forge never even enters the store." |
| 0:55–1:05 | No-authority + scope escape | Beats 4–5: purchase attempt → **REFUSE**; then Spoofer earns a real $50 grant and tries $800 → **REFUSE**. "Valid credential, wrong scope — caught deterministically." |
| 1:05–1:20 | Revocation | Beat 6: Acme revokes BuyerBot's authority (issuer re-signs the revocation). BuyerBot retries → **REFUSE**, receipt reads `revoked`. "Trust dies in seconds, verifiably." |
| 1:20–1:30 | Audit + thesis | Scroll the receipt log: every decision JSON, replayable, `llm_called=false`. Close: "In two years, agent identity = keys + scoped claims, not platform accounts. Thesis in the README." |

Backup: if the live URL misbehaves, `demo/run_demo.py` against localhost is the
identical flow; record the terminal + UI with any screen recorder.
