# Two-year thesis: agent memory done right

In two years, the agents we trust will not be the ones that remember the
most. They will be the ones whose memory is priced — every recollection
carrying what it cost to know and what it costs to be wrong.

Today's split — thin session state versus greedy vector dumps — fails the
same way from both ends: the agent either knows nothing about you or asserts
everything about you with equal, unearned confidence. The fix is not better
embeddings. It is making memory *accountable*.

Accountable memory has four properties, and we built all four as mechanics,
not marketing. First, provenance is mandatory: a fact that cannot name its
source does not get stored. Second, confidence is earned and decaying: what
you told me outweighs what I inferred; what I inferred once fades on a
schedule I can show you. Third, contradiction is a state, not an error: when
two claims conflict at equal strength, the honest system trusts neither and
says so. Fourth, forgetting is a right with teeth: revocation is
cryptographically signed, cascades to everything derived from the forgotten
fact, and leaves a tombstone — a receipt of what was erased and why.

The moat is calibration, and calibration cannot be bolted on after the fact.
A model that says "I might be wrong about this" at exactly the moments it
might be wrong is worth more than any retrieval benchmark, because it
converts memory from a liability into evidence. Users forgive an agent that
asks; they do not forgive one that confabulates their life back at them.

The open problem is standards: portable provenance formats and cross-vendor
revocation, so forgetting follows the user across agents the way the facts
already do. Whoever ships that protocol owns the trust layer of the agent
era. The winning memory is not the biggest one — it is the one that knows
its own limits.
