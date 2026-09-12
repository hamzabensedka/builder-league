# Thesis: two years past the chatbot

Chat is a fallback. It exists because the system doesn't know what you need,
so it makes you type it. Dashboards are the same failure pointed the other
way: the system can't decide what matters, so it shows you everything. Both
offload the machine's job — inference — onto the human's attention.

Within two years the default AI interface stops being a surface you operate
and becomes a **presence that interrupts correctly**. Three properties define
the winners:

**Inference over interrogation.** The interface watches state, not prompts.
The unit of interaction shifts from message to *decision*: the system folds
live events into a ranked hypothesis of what you need to decide next, and
shows exactly that — one thing, evidence chain attached. The hard engineering
is not generation; it is the restraint function deciding what *not* to
surface, and it must be inspectable — an interface you can't audit for
silence is just a quieter dashboard.

**Action before permission.** The interface initiates. When something risky
parks, the system has already simulated it, computed the before/after diff,
and pre-staged the rollback — the human's job collapses to approve, edit, or
reject. Confirm dialogs die; computed diffs replace them.

**Wrongness as a first-class path.** Any interface that infers will sometimes
infer wrong, so recovery can't be an error page — it has to be the mechanism.
A rejection is training signal: recorded, receipted, fed back, so the same
bad guess returns visibly demoted, and a second rejection degrades the system
gracefully to raw evidence instead of a third confident mistake. Trust in
ambient interfaces is earned precisely when they are wrong.

Chat won't disappear; it retreats to the edges — the novel request, the
exploration, the exception. The center moves to systems that already know.
The chatbot was the demo. The ambient canvas is the product.
