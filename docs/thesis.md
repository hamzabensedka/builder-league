# Two-Year Thesis: Agent Identity and Reputation at Scale

Within two years, the unit of agent trust stops being the platform account and
becomes the keypair. Agents will act across organizational boundaries —
negotiating, purchasing, deploying — long before any central registry can
certify them all, so trust has to travel *with the claim*, not with the
platform that issued it. Verifiable credentials signed with ordinary public-key
cryptography (Ed25519 today) are the only model that scales: any counterparty
can verify a claim offline, without phoning home to an issuer.

Three consequences follow. First, reputation stops being a scalar. A single
score is un-auditable and gameable; what survives is the claim graph — a set of
specific, signed, scoped, expirable statements (this agent may spend up to X;
it completed Y tasks; Z vouches for it) that every verifier can inspect and
trace. Second, enforcement must be deterministic. The moment an LLM is the
gatekeeper, trust becomes a prompt-injection problem; policy engines, not
models, decide allow/refuse, and models are reserved for the judgment calls in
between. Third, revocation becomes the hard problem. Issuance is easy; the
systems that win are the ones where a compromised agent's authority dies in
seconds, verifiably, and every refusal it provokes leaves a receipt.

The stack that emerges looks like what this project prototypes: keys as
identity, VC-shaped claims as reputation, policy engines as enforcement, and
append-only decision receipts as the audit layer that makes all of it legible
to the humans ultimately responsible.
