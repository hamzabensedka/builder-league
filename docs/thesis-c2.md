# Two-year thesis: where decision layers go next

In two years, no production agent acts without passing through an explicit
decision layer — and that layer will be judged on its refusals, not its
executions. The valuable artifact is the *negative*: the action that was
asked about, deferred, escalated, or refused, with the exact signal vector
that caused it. Execution is cheap; knowing when not to is the product.

Three shifts define the direction. First, **decision layers become standing
infrastructure**, like API gateways: a single enforcement point every agent
write crosses, composable across domains, with per-domain policy as data. The
five outcomes harden into a standard vocabulary — `execute/ask/defer/escalate/
refuse` becomes the HTTP status line of agentic work.

Second, **evidence becomes typed and verifiable**. Today the engine trusts
context fields an actor supplies (`tests_passing: true`). Within two years
those fields carry provenance — signed CI attestations, signed change tickets
— so `evidence` and `authority` merge into one verifiable claim graph, and
"missing information" becomes a machine-checkable gap an orchestrator can
fill automatically before re-asking.

Third, **the audit trail becomes the training signal**. Every receipted
decision — especially the near-misses where a high-confidence action was
still refused — is labeled data about the boundary between safe and unsafe.
Decision layers will tune their own thresholds from their own append-only
logs, closing the loop C8 started: simulate, decide, receipt, learn.

The systems that win are not the ones that act most; they are the ones whose
refusals are precise, named, and reversible. The decision layer is the trust
layer — and it is deterministic by design, because a guess you cannot explain
is a liability you cannot audit.
