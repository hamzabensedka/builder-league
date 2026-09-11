# C4 demo script — 90 seconds: "Maya knows she might be wrong"

Live URL → open the **C4 · Memory** tab. Everything below is one click per
beat, server-side on the real stack. Total: ~90 seconds.

## Setup (0:00–0:10)

1. Press **Run the demo**. Maya learns three facts about you, each tagged
   differently: "prefers window seat" (you said it — 95%), "lives in Lisbon"
   (inferred once from a booking email — 40%), "flies TAP" (CRM import —
   30-day TTL). The inspector shows all three with source badge, confidence
   bar, scope, and freshness.

## The "I'm not sure" moment (0:10–0:30)

2. Press **2 · Plan a trip**. Two reliance receipts appear. Seat: **Confident**
   — she'll book the window. City: amber **"I might be wrong about this"** —
   40% calibrated, below the 55% acting threshold, gap named: low confidence,
   corroboration needed. She half-trusts Lisbon and says so instead of
   acting on it. *This is the moment the brief asks for.*

## Contradiction (0:30–0:50)

3. Press **3 · User corrects: moved to Porto**. Your stated correction
   decisively supersedes the weak inference — Lisbon is struck through in
   the forgetting feed with reason `superseded`, and the new city recall is
   Confident on Porto. The old belief wasn't overwritten; it was receipted.

## Staleness (0:50–1:05)

4. Press **4 · Time passes**. 45 simulated days later the sweeper kills the
   CRM import — TTL expired — and the airline recall now returns "I don't
   know". Ask Maya **airline** to confirm: nothing relied on, gap named.

## Privacy revocation (1:05–1:25)

5. Press **5 · Sign "forget my location"**. A real Ed25519-signed revocation
   tombstones the Porto fact (and would cascade to anything derived from
   it). City recall goes blank; the tombstone shows `revoked`. Ask **city** —
   Maya no longer knows, and can show you the receipt of forgetting.

## Close (1:25–1:30)

6. Point at the inspector: live facts with tags on the left, reliance
   receipts in the middle, tombstones with reasons on the right. Three
   panels, one claim: memory that knows what it knows, what it doesn't, and
   when to forget.

## Failure paths (if asked)

- `tests/test_memory_failure.py`: equal-strength contradiction → trusts
  neither; stale import → never relied on; forged revocation signature →
  403, nothing changes; task/user scope → never leaks.
