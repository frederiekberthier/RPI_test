"""De toestandsmachine achter het scherm: wacht op de DUT, start een run op een knop, houdt
de voortgang bij en bewaart het rapport. Geen HTTP of HTML hier, zodat het los te testen is."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from .. import report as report_mod
from ..factory import ContextFactory
from ..models import CheckResult, Report
from ..runner import CHECK_GROUPS, Check, Progress, run_all

GROUP_LABELS = {
    "connect": "Verbinding met de DUT",
    "gpio": "GPIO-pinnen",
    "usb": "USB-poorten",
    "network": "Netwerk (bedraad)",
    "wifi": "Wifi",
    "bluetooth": "Bluetooth",
    "power": "Voeding, temperatuur en belasting",
}


class Controller:
    def __init__(self, make_context: ContextFactory, probe: Callable[[], dict | None], reports_dir: Path,
                 groups: dict[str, Check] | None = None, clock: Callable[[], float] = time.monotonic):
        self._make_context = make_context
        self._probe = probe
        self._reports_dir = reports_dir
        self._groups = CHECK_GROUPS if groups is None else groups
        self._clock = clock
        self._lock = threading.Lock()
        self._phase = "idle"  # idle | running | done
        self._dut: dict = {"ready": False, "info": None}
        self._run: dict = {}
        self._last: dict | None = None
        self._abort = False
        self._thread: threading.Thread | None = None
        self._stop_polling = threading.Event()

    # ---------------------------------------------------------------- DUT-detectie
    def refresh_dut(self) -> None:
        """Eén controle of de DUT bereikbaar is. Tijdens een run wordt er niet gecontroleerd."""
        with self._lock:
            if self._phase == "running":
                return
        info = self._probe()
        with self._lock:
            if self._phase != "running":
                self._dut = {"ready": info is not None, "info": info}

    def start_polling(self, interval: float = 2.0) -> threading.Thread:
        def loop() -> None:
            while not self._stop_polling.wait(interval):
                try:
                    self.refresh_dut()
                except Exception:  # de detectie mag nooit de server doden
                    pass

        thread = threading.Thread(target=loop, daemon=True, name="dut-probe")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop_polling.set()

    # ---------------------------------------------------------------- acties
    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._phase == "running":
                return False, "er loopt al een test"
            if self._phase == "done":
                return False, "druk eerst op 'Nieuwe test'"
            if not self._dut["ready"]:
                return False, "de DUT is nog niet bereikbaar"
            self._phase = "running"
            self._abort = False
            self._run = {
                "started": self._clock(), "current": None, "results": [], "error": None,
                "groups": [{"key": k, "label": GROUP_LABELS.get(k, k), "status": "wachten"}
                           for k in ("connect", *self._groups)],
            }
            self._last = None
            self._thread = threading.Thread(target=self._execute, daemon=True, name="testrun")
            self._thread.start()
        return True, "gestart"

    def abort(self) -> tuple[bool, str]:
        with self._lock:
            if self._phase != "running":
                return False, "er loopt geen test"
            self._abort = True
        return True, "stopt na het huidige onderdeel"

    def reset(self) -> tuple[bool, str]:
        with self._lock:
            if self._phase == "running":
                return False, "er loopt nog een test"
            self._phase = "idle"
            self._run, self._last = {}, None
        self.refresh_dut()
        return True, "klaar voor een nieuwe test"

    def join(self, timeout: float | None = None) -> None:
        """Wacht tot een lopende run klaar is (voor tests)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ---------------------------------------------------------------- de run zelf
    def _execute(self) -> None:
        close = None
        try:
            ctx, close = self._make_context()
            report = run_all(ctx, self._groups, _RunProgress(self))
            self._finish(report)
        except Exception as exc:  # bv. GPIO niet te openen: toon het op het scherm
            with self._lock:
                self._close_current("fout")
                self._run["error"] = f"{type(exc).__name__}: {exc}"
                self._last = {"overall": "FAIL", "html": None, "error": self._run["error"]}
                self._phase = "done"
        finally:
            if close is not None:
                try:
                    close()
                except Exception:
                    pass

    def _finish(self, report: Report) -> None:
        _, html_path = report_mod.save(report, self._reports_dir)
        with self._lock:
            self._close_current()
            self._run["current"] = None
            self._last = {"overall": report.overall, "html": html_path.name, "error": None}
            self._phase = "done"

    # ---------------------------------------------------------------- voortgang (door _RunProgress)
    def _set_group(self, key: str | None, status: str) -> None:
        for g in self._run["groups"]:
            if g["key"] == key:
                g["status"] = status

    def _close_current(self, status: str = "klaar") -> None:
        for g in self._run["groups"]:
            if g["status"] == "bezig":
                g["status"] = status

    def _group_started(self, name: str) -> None:
        with self._lock:
            self._close_current()  # de vorige groep is hiermee klaar
            self._run["current"] = name
            self._set_group(name, "bezig")

    def _result(self, result: CheckResult) -> None:
        with self._lock:
            self._run["results"].append({"name": result.name, "status": result.status.value,
                                         "summary": result.summary})
            if result.status.value == "SKIP":  # een overgeslagen groep heeft de groepsnaam als resultaatnaam
                self._set_group(result.name, "overgeslagen")

    def _should_stop(self) -> bool:
        return self._abort

    # ---------------------------------------------------------------- toestand voor het scherm
    def state(self) -> dict:
        with self._lock:
            run = dict(self._run) if self._run else {}
            elapsed = round(self._clock() - run["started"], 1) if run else 0.0
            state = {
                "phase": self._phase,
                "dut": dict(self._dut),
                "abort_requested": self._abort,
                "elapsed": elapsed,
                "current": run.get("current"),
                "groups": [dict(g) for g in run.get("groups", [])],
                "results": list(run.get("results", [])),
                "last": dict(self._last) if self._last else None,
            }
        state["history"] = report_mod.list_history(self._reports_dir)
        return state


class _RunProgress(Progress):
    def __init__(self, controller: Controller):
        self._c = controller

    def group_started(self, name: str) -> None:
        self._c._group_started(name)

    def result(self, result: CheckResult) -> None:
        self._c._result(result)

    def should_stop(self) -> bool:
        return self._c._should_stop()
