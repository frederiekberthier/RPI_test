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


# ---------------------------------------------------------------- afsluiten (applicatie of Pi, en de TEST-CLIENT)

IDLE = {**BASE_STATE, "phase": "idle", "shutdown_allowed": True, "elapsed": 0,
        "client": {"ready": True, "info": {"model": "Pi", "serial": "X1"}}}


def test_the_exit_button_is_visible_when_allowed_and_disabled_during_a_test():
    result = run_scenario("""
        await refresh();
        const idle = [__el("exit-btn").classList.contains("hidden"), __el("exit-btn").disabled];
        __setState({...state, phase: "running"});
        await refresh();
        return [idle, [__el("exit-btn").classList.contains("hidden"), __el("exit-btn").disabled]];
    """, IDLE)
    assert result == [[False, False], [False, True]]
    hidden = run_scenario('await refresh(); return __el("exit-btn").classList.contains("hidden");',
                          {**IDLE, "shutdown_allowed": False})
    assert hidden is True


def test_the_dialog_first_asks_what_to_close_and_then_whether_the_client_must_follow():
    result = run_scenario("""
        await refresh();
        openExit();
        const opened = [!__el("exit-dialog").classList.contains("hidden"), !__el("exit-step1").classList.contains("hidden")];
        chooseExit("poweroff");
        const asked = [__el("exit-step2").classList.contains("hidden"), __bodies.length, __el("exit-client-question").textContent];
        await sendExit(true);
        return [opened, asked, __bodies, !__el("closing").classList.contains("hidden"), __el("closing-text").textContent];
    """, IDLE)
    opened, asked, bodies, closing, text = result
    assert opened == [True, True]
    assert asked[0] is False and asked[1] == 0 and "TEST-SERVER wordt uitgeschakeld" in asked[2]  # nog niets verstuurd
    assert bodies == [["/api/shutdown", {"confirm": True, "mode": "poweroff", "client": True}]]
    assert closing is True and "TEST-CLIENT wordt ook uitgeschakeld" in text


def test_closing_only_the_application_and_keeping_the_client_on():
    result = run_scenario("""
        await refresh();
        openExit();
        chooseExit("app");
        await sendExit(false);
        return [__bodies, __el("closing-title").textContent, __el("closing-text").textContent];
    """, IDLE)
    assert result[0] == [["/api/shutdown", {"confirm": True, "mode": "app", "client": False}]]
    assert result[1] == "De applicatie wordt gesloten" and "TEST-CLIENT" not in result[2]


def test_without_a_connected_client_there_is_no_client_question():
    result = run_scenario("""
        await refresh();
        openExit();
        chooseExit("app");
        await Promise.resolve();
        await Promise.resolve();
        return [__bodies, __el("exit-step2").classList.contains("hidden")];
    """, {**IDLE, "client": {"ready": False, "info": None}})
    assert result[0] == [["/api/shutdown", {"confirm": True, "mode": "app", "client": False}]]
    assert result[1] is True


def test_a_refusal_keeps_the_dialog_open_and_shows_the_reason():
    result = run_scenario("""
        __setPost("/api/shutdown", {ok: false, message: "de TEST-CLIENT is niet uitgeschakeld (time-out); er is niets afgesloten"});
        await refresh();
        openExit();
        chooseExit("poweroff");
        await sendExit(true);
        return [__el("exit-error").textContent, __el("closing").classList.contains("hidden"),
                __el("exit-dialog").classList.contains("hidden"), __el("exit-step1").classList.contains("hidden")];
    """, IDLE)
    assert result == ["de TEST-CLIENT is niet uitgeschakeld (time-out); er is niets afgesloten", True, False, False]


def test_the_dialog_cannot_be_opened_during_a_test_and_can_be_cancelled():
    result = run_scenario("""
        await refresh();
        __setState({...state, phase: "running"});
        await refresh();
        openExit();
        const duringTest = __el("exit-dialog").classList.contains("hidden");
        __setState({...state, phase: "idle"});
        await refresh();
        openExit();
        closeExit();
        return [duringTest, __el("exit-dialog").classList.contains("hidden")];
    """, IDLE)
    assert result == [True, True]


def test_enter_does_not_start_a_test_while_the_dialog_is_open_and_escape_closes_it():
    result = run_scenario("""
        await refresh();
        openExit();
        __fire("keydown", {key: "Enter"});
        await Promise.resolve();
        const started = __bodies.length;
        __fire("keydown", {key: "Escape"});
        const closed = __el("exit-dialog").classList.contains("hidden");
        __fire("keydown", {key: "Enter"});     // zonder dialoog start dezelfde toets weer een test
        await Promise.resolve();
        return [started, closed, __bodies.map(b => b[0])];
    """, IDLE)
    assert result == [0, True, ["/api/start"]]


def test_the_old_confirm_dialog_and_footer_button_are_gone():
    page = PAGE.read_text(encoding="utf-8")
    assert "confirm(" not in page and 'id="shutdown"' not in page
