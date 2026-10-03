from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field


class Status(str, enum.Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"  # niet uitgevoerd (bv. omdat de DUT onbereikbaar is)


@dataclass
class CheckResult:
    name: str
    status: Status
    summary: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class Report:
    tester_info: dict
    dut_info: dict
    results: list[CheckResult]
    started: str
    finished: str

    @property
    def overall(self) -> str:
        """FAIL > INCOMPLETE (er is iets overgeslagen) > WARN > PASS."""
        statuses = {r.status for r in self.results}
        if Status.FAIL in statuses:
            return "FAIL"
        if Status.SKIP in statuses:
            return "INCOMPLETE"
        if Status.WARN in statuses:
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["overall"] = self.overall
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
