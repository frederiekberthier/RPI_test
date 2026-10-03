"""Test de JavaScript van het scherm met Node.js tegen een nagebootste DOM (tests/ui_harness.js)."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")
HERE = Path(__file__).parent
PAGE = HERE.parent / "rpitest" / "ui" / "static" / "index.html"
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js niet beschikbaar")

BASE_STATE = {
    "phase": "running", "client": {"ready": True, "info": {"model": "Pi", "serial": "X1"}}, "abort_requested": False,
    "elapsed": 12.0, "current": "wifi", "results": [], "last": None, "history": [], "shutdown_allowed": False,
    "groups": [],
}


def run_scenario(body: str, state: dict | None = None):
    """Voert `async function scenario() { ... }` uit nadat de pagina is geladen met `state` als eerste toestand."""
    source = f"__setState({json.dumps(state or BASE_STATE)});\nasync function scenario() {{\n{body}\n}}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(source)
        scenario = f.name
    proc = subprocess.run([NODE, str(HERE / "ui_harness.js"), str(PAGE), scenario], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def group(key, status):
    return {"key": key, "label": key.upper(), "status": status}


# ---------------------------------------------------------------- issue #19

def test_group_chips_show_failed_and_warning_groups_distinctly():
    state = {**BASE_STATE, "phase": "done", "last": {"overall": "FAIL", "html": "r.html", "error": None},
             "groups": [group("connect", "klaar"), group("gpio", "fout"), group("wifi", "waarschuwing"),
                        group("usb", "overgeslagen")]}
    chips = run_scenario("""
        await refresh();
        return __el("groups").children.map(c => [c.className, c.textContent]);
    """, state)
    assert chips == [["klaar", "CONNECT: klaar"], ["fout", "GPIO: fout"], ["waarschuwing", "WIFI: waarschuwing"],
                     ["overgeslagen", "USB: overgeslagen"]]


def test_the_page_styles_the_failed_and_warning_chips():
    css = PAGE.read_text(encoding="utf-8")
    assert "#groups li.fout" in css and "#groups li.waarschuwing" in css


# ---------------------------------------------------------------- issue #20

def test_a_server_message_survives_the_refresh_that_follows_it_and_then_expires():
    state = {**BASE_STATE, "phase": "done", "last": {"overall": "PASS", "html": None, "error": None}}
    shown = run_scenario("""
        __setPost("/api/reset", {ok: false, message: "er loopt al een test"});
        await post("/api/reset", {});
        const direct = __el("hint").textContent;           // direct na de mislukte opdracht en de refresh erna
        await refresh();
        const later = __el("hint").textContent;            // de volgende poll binnen de tijd
        __setNow(1_000_000 + 5000);
        await refresh();
        return [direct, later, __el("hint").textContent];
    """, state)
    assert shown == ["er loopt al een test", "er loopt al een test", "Wissel de Pi, of druk op de knop om opnieuw te beginnen."]


def test_a_failed_request_is_reported_and_also_survives_the_refresh():
    shown = run_scenario("""
        const original = fetch;
        fetch = async () => { throw new Error("offline"); };
        await post("/api/start", {});
        return __el("hint").textContent;
    """)
    assert shown == "Kon de opdracht niet versturen."
