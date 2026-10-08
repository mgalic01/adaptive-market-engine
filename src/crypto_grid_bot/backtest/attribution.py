"""Reporting-only attribution. No strategy or account reads these records."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class EntryAttribution:
    """One detail row per selected Uptrend opportunity, not per quote.

    Continuation outcomes count buy attempts, not independent trades. Old reports
    without the additive field are accepted. Decimal values serialize as strings.
    """

    records: list[dict[str, Any]] = field(default_factory=list)
    selected_outcomes: Counter[str] = field(default_factory=Counter)
    continuation_outcomes: Counter[str] = field(default_factory=Counter)

    def record(self, report: dict[str, Any]) -> None:
        entry = report.get("uptrend_entry")
        if entry is None:
            return
        if entry["selected"]:
            self.records.append(
                {k: str(v) if isinstance(v, Decimal) else deepcopy(v) for k, v in entry.items()}
            )
            self.selected_outcomes[entry["outcome"]] += 1
        else:
            self.continuation_outcomes[entry["outcome"]] += 1

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "selected": len(self.records),
            "selected_outcomes": dict(sorted(self.selected_outcomes.items())),
            "continuation_outcomes": dict(sorted(self.continuation_outcomes.items())),
            "records": deepcopy(self.records),
        }
