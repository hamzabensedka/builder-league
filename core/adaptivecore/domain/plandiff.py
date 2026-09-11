"""PlanDiff — the computed before/after of a re-plan. Never narrated.

Pure domain. The diff is structural: which steps were added, removed, or
changed (which field, from what, to what). The "I changed my mind because…"
card renders this verbatim.
"""

from dataclasses import dataclass, field
from typing import Any

from core.adaptivecore.domain.plans import Plan, PlanStep


@dataclass(frozen=True)
class StepChange:
    step_id: str
    action: str
    field: str
    before: Any
    after: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "field": self.field,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class PlanDiff:
    added: list[PlanStep] = field(default_factory=list)
    removed: list[PlanStep] = field(default_factory=list)
    changed: list[StepChange] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": [s.as_dict() for s in self.added],
            "removed": [s.as_dict() for s in self.removed],
            "changed": [c.as_dict() for c in self.changed],
            "summary": self.summary,
        }


def diff_plans(old: Plan, new: Plan) -> PlanDiff:
    """Structural diff old → new over the steps the re-plan actually touches:
    the revised (pending) steps plus any step whose status CHANGED (a cascade
    that re-opens an executed step is a real delta, shown as such)."""
    old_all = {s.action: s for s in old.steps}
    new_all = {s.action: s for s in new.steps}
    relevant = [
        a for a in set(old_all) | set(new_all)
        if (old_all.get(a) is not None and old_all[a].status != "done")
        or (new_all.get(a) is not None and new_all[a].status != "done")
        or ((old_all.get(a) is not None and new_all.get(a) is not None)
            and old_all[a].status != new_all[a].status)
    ]

    added = [new_all[a] for a in relevant if a in new_all and a not in old_all]
    removed = [old_all[a] for a in relevant if a in old_all and a not in new_all]

    changed: list[StepChange] = []
    for action in relevant:
        old_step, new_step = old_all.get(action), new_all.get(action)
        if old_step is None or new_step is None:
            continue
        if old_step.status != new_step.status:
            changed.append(StepChange(
                step_id=new_step.id, action=action, field="status",
                before=old_step.status, after=new_step.status,
            ))
        keys = set(old_step.params) | set(new_step.params)
        for k in sorted(keys):
            before, after = old_step.params.get(k), new_step.params.get(k)
            if before != after:
                changed.append(StepChange(
                    step_id=new_step.id, action=action, field=k,
                    before=before, after=after,
                ))

    parts: list[str] = []
    for c in changed:
        parts.append(f"{c.action}: {c.field} {c.before} → {c.after}")
    for s in added:
        parts.append(f"+{s.action}")
    for s in removed:
        parts.append(f"−{s.action}")
    summary = "; ".join(parts) if parts else "no structural change"

    return PlanDiff(added=added, removed=removed, changed=changed, summary=summary)
