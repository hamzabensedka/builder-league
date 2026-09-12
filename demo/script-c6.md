# C6 Demo Script — 90 seconds (a simulated day + the three beats)

Open the UI → **C6 · Company** tab.

**Setup (5s).** Press **Seed Northwind Components**. Four roles enroll with
signed, scoped authority; the opening books appear: $50,000 cash, 200 units,
2 invoices, 1 bill. The KPI bar lights up.

**Beat 1 — a normal day runs (25s).** Press **▶ Run a day**. Leads arrive,
SalesBot quotes the biggest one and wins it (invoice issued), OpsBot restocks,
FinanceBot collects a due invoice and pays a due bill. Watch the numbers move:
revenue up, cash shifted, runway recomputed. If an action is borderline it
parks in the **human inbox** — type "approved" and resolve it. That inline
answer is the human-in-the-loop moment.

**Beat 2 — self-correction, zero human input (30s).** Press **⚡ Cash crunch**,
then run two days. A big customer churns and a supplier bill lands early —
runway drops under 21 days and turns red. With no human clicking anything:
FinanceBot freezes discretionary spend, OpsBot defers the restock, SalesBot
prioritizes collections, and the ChiefOfStaff ratifies the freeze. Run two
more days and watch runway recover. The company held itself together.

**Beat 3 — failure test: Sales goes rogue (25s).** Press **☠ Rogue sales** and
run days. SalesBot starts over-discounting — but its quotes are over its signed
$5k scope, so TrustCore **refuses** them cryptographically. After a refusal
streak the spine records `role_paused` and SalesBot flips to *paused* while Ops
and Finance protect the books. Replay SalesBot's reasoning on the timeline,
then read the escalation. The failure was contained, not ignored.

**Close (5s).** Drag the **replay** scrubber back to any earlier day — the whole
board re-folds from the event log. Every number you saw is a fold over one
append-only record, replayable end to end.
