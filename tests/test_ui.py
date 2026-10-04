import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from rpitest import factory
from rpitest import report as report_mod
from rpitest.agent.client import RemoteGpioPort, RpcClient
from rpitest.context import Context
from rpitest.gpio.mock import SERVER, MockWiring
from rpitest.models import CheckResult, Report, Status
from rpitest.ui import server as ui_server
from rpitest.ui.controller import Controller


def mock_factory(*faults):
    return lambda: factory.mock_context(list(faults))


def wait_until(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("time-out")


def make_controller(tmp_path, groups=None, make_context=None, probe=factory.mock_probe):
    c = Controller(make_context or mock_factory(), probe, tmp_path, groups)
    c.refresh_client()
    return c


def run_to_end(c):
    ok, message = c.start()
    assert ok, message
    c.join(60)
    return c.state()


# ---------------------------------------------------------------- controller

def test_full_mock_run_ends_with_report_and_all_groups_done(tmp_path):
    c = make_controller(tmp_path)
    s = run_to_end(c)
    assert s["phase"] == "done" and s["last"]["overall"] == "PASS"
    assert all(g["status"] == "klaar" for g in s["groups"]), s["groups"]
    assert (tmp_path / s["last"]["html"]).is_file()
    assert {"gpio.pulls", "net.link", "wifi.radio", "bt.controller", "power.cpu"} <= {r["name"] for r in s["results"]}
    assert s["history"][0]["serial"] == "MOCK0001" and s["history"][0]["overall"] == "PASS"


def test_start_is_refused_until_the_client_is_ready(tmp_path):
    ready = {"value": None}
    c = make_controller(tmp_path, probe=lambda: ready["value"])
    assert c.start() == (False, "de TEST-CLIENT is nog niet bereikbaar")
    ready["value"] = {"model": "Pi", "serial": "X1"}
    c.refresh_client()
    assert c.state()["client"] == {"ready": True, "info": {"model": "Pi", "serial": "X1"}}
    ready["value"] = None  # kabel eruit
    c.refresh_client()
    assert c.state()["client"]["ready"] is False


def test_second_start_while_running_and_client_probe_paused_during_run(tmp_path):
    gate, started = threading.Event(), threading.Event()

    def slow(ctx):
        started.set()
        gate.wait(30)
        return [CheckResult("slow", Status.PASS, "ok")]

    probes = []
    c = make_controller(tmp_path, {"slow": slow}, probe=lambda: probes.append(1) or {"serial": "S"})
    assert c.start()[0]
    started.wait(30)
    assert c.start() == (False, "er loopt al een test")
    assert c.reset() == (False, "er loopt nog een test")
    before = len(probes)
    c.refresh_client()
    assert len(probes) == before  # tijdens de run wordt de TEST-CLIENT niet gecontroleerd
    assert c.state()["phase"] == "running" and c.state()["current"] == "slow"
    gate.set()
    c.join(30)
    assert c.state()["phase"] == "done"


def test_abort_skips_remaining_groups_and_gives_incomplete(tmp_path):
    gate, started = threading.Event(), threading.Event()

    def first(ctx):
        started.set()
        gate.wait(30)
        return [CheckResult("first", Status.PASS, "ok")]

    def second(ctx):
        raise AssertionError("mag niet meer draaien")

    c = make_controller(tmp_path, {"first": first, "second": second})
    c.start()
    started.wait(30)
    assert c.abort()[0] and c.state()["abort_requested"]
    gate.set()
    c.join(30)
    s = c.state()
    assert s["last"]["overall"] == "INCOMPLETE"
    assert [g["status"] for g in s["groups"]] == ["klaar", "klaar", "overgeslagen"]
    assert "afgebroken" in s["results"][-1]["summary"]
    assert c.abort() == (False, "er loopt geen test")


def test_reset_goes_back_to_idle_and_allows_a_new_run(tmp_path):
    c = make_controller(tmp_path)
    assert c.reset() == (True, "klaar voor een nieuwe test")  # ook vanuit idle onschadelijk
    run_to_end(c)
    assert c.start() == (False, "druk eerst op 'Nieuwe test'")
    assert c.reset()[0]
    s = c.state()
    assert s["phase"] == "idle" and s["results"] == [] and s["last"] is None
    assert run_to_end(c)["phase"] == "done"
    assert len(c.state()["history"]) == 2 and len(list(tmp_path.glob("report-*.json"))) == 2
    assert len(list(tmp_path.glob("report-*.html"))) == 2  # twee runs binnen één seconde overschrijven elkaar niet


def test_context_error_is_shown_instead_of_crashing(tmp_path):
    def broken():
        raise RuntimeError("GPIO-lijnen in gebruik: 2, 3")

    c = make_controller(tmp_path, make_context=broken)
    s = run_to_end(c)
    assert s["phase"] == "done" and s["last"]["overall"] == "FAIL" and s["last"]["html"] is None
    assert "GPIO-lijnen in gebruik" in s["last"]["error"]


def test_closer_runs_after_every_run_even_when_a_check_crashes(tmp_path):
    closed = []

    def make():
        ctx, _ = factory.mock_context([])
        return ctx, lambda: closed.append(1)

    def crash(ctx):
        raise ValueError("kapot")

    c = make_controller(tmp_path, {"crash": crash}, make_context=make)
    s = run_to_end(c)
    assert closed == [1]
    assert s["results"][-1]["status"] == "FAIL" and "gecrasht" in s["results"][-1]["summary"]


def test_unreachable_client_marks_every_group_skipped(tmp_path):
    def unreachable():
        client = RpcClient("http://127.0.0.1:9", timeout=0.3)
        wiring = MockWiring()
        return Context(wiring.port(SERVER), RemoteGpioPort(client), client, {}), (lambda: None)

    c = make_controller(tmp_path, make_context=unreachable)
    s = run_to_end(c)
    assert s["last"]["overall"] == "FAIL"
    assert [g["status"] for g in s["groups"]][1:] == ["overgeslagen"] * (len(s["groups"]) - 1)


def test_history_ignores_broken_files(tmp_path):
    (tmp_path / "report-kapot.json").write_text("{niet json")
    (tmp_path / "report-leeg.json").write_text("{}")
    assert report_mod.list_history(tmp_path) == []


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def web(tmp_path):
    controller = make_controller(tmp_path)
    srv = ui_server.make_server(controller, tmp_path, "127.0.0.1", 0, allow_shutdown=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]

    def request(method, path, body=None, host=None, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        sent = {"Host": host} if host else {}
        if method == "POST":
            sent["Content-Type"] = "application/json"  # zoals de pagina; een test kan dat overschrijven
        sent.update(headers or {})
        headers = sent
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    request.port = port
    yield controller, request, tmp_path
    srv.shutdown()
    srv.server_close()


def test_page_and_state_are_served(web):
    controller, request, _ = web
    status, body = request("GET", "/")
    assert status == 200 and b"Raspberry Pi tester" in body
    status, body = request("GET", "/api/state")
    state = json.loads(body)
    assert status == 200 and state["phase"] == "idle" and state["client"]["ready"] and state["shutdown_allowed"]


def test_start_over_http_then_report_is_downloadable(web):
    controller, request, tmp_path = web
    status, body = request("POST", "/api/start")
    assert status == 200 and json.loads(body)["ok"]
    controller.join(60)
    state = json.loads(request("GET", "/api/state")[1])
    assert state["phase"] == "done"
    status, body = request("GET", "/reports/" + state["last"]["html"])
    assert status == 200 and b"PASS" in body and b"MOCK0001" in body
    status, _ = request("GET", "/reports/" + state["last"]["html"].replace(".html", ".json"))
    assert status == 200
    assert request("POST", "/api/start")[0] == 409  # eerst 'Nieuwe test'
    assert request("POST", "/api/reset")[0] == 200


@pytest.mark.parametrize("path", [
    # deze bestaan echt (naast de rapportmap), dus alleen een echte controle houdt ze tegen
    "/reports/../secret.html", "/reports/..%2Fsecret.html", "/reports/%2e%2e/secret.html", "/reports/..\\secret.html",
    "/reports/../report-geheim.html", "/reports/..%2Freport-geheim.json", "/reports/%2e%2e%2freport-geheim.html",
    # en gewone weigeringen
    "/reports/secret.html", "/reports/report-.html/..", "/reports/", "/reports/report-x.exe", "/nietbestaand",
])
def test_report_route_cannot_leave_the_reports_folder(web, path):
    _, request, tmp_path = web
    (tmp_path.parent / "secret.html").write_text("geheim")
    (tmp_path.parent / "report-geheim.html").write_text("geheim")
    (tmp_path.parent / "report-geheim.json").write_text("geheim")
    status, body = request("GET", path)
    assert status == 404 and b"geheim" not in body


def test_report_route_serves_a_valid_name(web):
    _, request, tmp_path = web
    (tmp_path / "report-ok-1.html").write_text("<p>zichtbaar</p>")
    status, body = request("GET", "/reports/report-ok-1.html")
    assert status == 200 and b"zichtbaar" in body


def test_foreign_host_header_is_refused(web):
    _, request, _ = web
    assert request("GET", "/api/state", host="evil.example")[0] == 403
    assert request("POST", "/api/start", {}, host="evil.example")[0] == 403
    assert request("GET", "/api/state", host="localhost:1")[0] == 403  # verkeerde poort


def test_rejected_post_with_a_body_still_gets_a_clean_response(web):
    # Regressie: een geweigerde POST waarvan de body ongelezen bleef, brak de verbinding af (Windows: 10053)
    _, request, _ = web
    big = {"padding": "x" * 50_000}
    for _ in range(20):
        assert request("POST", "/api/start", big, host="evil.example")[0] == 403
        assert request("POST", "/api/onbekend", big)[0] == 404


def test_oversized_body_is_refused(web):
    _, request, _ = web
    assert request("POST", "/api/start", {"padding": "x" * 100_000})[0] == 400


def test_bad_json_and_unknown_post_route(web):
    _, request, _ = web
    assert request("POST", "/api/start", raw=b"{dit is geen json")[0] == 400
    assert request("POST", "/api/onbekend", {})[0] == 404


def test_shutdown_needs_confirmation_and_is_blocked_while_running(web, monkeypatch):
    controller, request, _ = web
    calls = []
    monkeypatch.setattr(ui_server.subprocess, "Popen", lambda argv: calls.append(argv))
    assert request("POST", "/api/shutdown", {})[0] == 400
    assert request("POST", "/api/shutdown", {"confirm": "ja"})[0] == 400
    assert calls == []
    gate = threading.Event()
    controller._groups = {"slow": lambda ctx: (gate.wait(30), [CheckResult("slow", Status.PASS, "ok")])[1]}
    controller.start()
    wait_until(lambda: controller.state()["phase"] == "running")
    assert request("POST", "/api/shutdown", {"confirm": True})[0] == 409
    gate.set()
    controller.join(30)
    assert calls == []
    assert request("POST", "/api/shutdown", {"confirm": True})[0] == 200
    # de server stuurt eerst het antwoord en voert het commando daarna uit: even op de oproep wachten
    wait_until(lambda: calls)
    assert calls == [["systemctl", "poweroff"]]


def test_shutdown_is_disabled_by_default(tmp_path, monkeypatch):
    controller = make_controller(tmp_path)
    srv = ui_server.make_server(controller, tmp_path, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ui_server.subprocess, "Popen", lambda argv: pytest.fail("mag niet uitschakelen"))
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("POST", "/api/shutdown", json.dumps({"confirm": True}), {"Content-Type": "application/json"})
        assert conn.getresponse().status == 403
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- pagina en rapport

def test_page_never_uses_innerhtml():
    page = (Path(ui_server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in page and "outerHTML" not in page and "document.write" not in page


def test_report_escapes_hostile_text_from_the_client():
    hostile = '<script>alert(1)</script>'
    report = Report({"model": "T"}, {"model": hostile, "serial": hostile},
                    [CheckResult("usb.SLOT1", Status.FAIL, hostile, {"product": hostile})], "2026-10-03T10:00:00",
                    "2026-10-03T10:01:00")
    page = report_mod.to_html(report)
    assert hostile not in page and "&lt;script&gt;" in page


def test_report_filename_is_sanitised(tmp_path):
    report = Report({}, {"serial": "../../etc/passwd"}, [], "2026-10-03T10:00:00", "2026-10-03T10:01:00")
    json_path, html_path = report_mod.save(report, tmp_path / "rapporten")
    assert json_path.parent == tmp_path / "rapporten" and report_mod.REPORT_NAME.match(html_path.name)


# ---------------------------------------------------------------- issue #19: groepsstatus bij FAIL en WARN

def group_status(state):
    return {g["key"]: g["status"] for g in state["groups"]}


def test_a_failing_group_is_marked_as_failed_not_done(tmp_path):
    c = make_controller(tmp_path, make_context=mock_factory("stuck_low:C:5"))
    status = group_status(run_to_end(c))
    assert status["gpio"] == "fout"
    assert status["connect"] == "klaar" and status["usb"] == "klaar" and status["network"] == "klaar"


def test_a_group_with_only_warnings_is_marked_as_warning(tmp_path):
    c = make_controller(tmp_path, make_context=mock_factory("wifi_weak"))
    status = group_status(run_to_end(c))
    assert status["wifi"] == "waarschuwing" and status["gpio"] == "klaar"


def test_a_failed_connection_shows_as_failed(tmp_path):
    def unreachable():
        client = RpcClient("http://127.0.0.1:9", timeout=0.3)
        return Context(MockWiring().port(SERVER), RemoteGpioPort(client), client, {}), (lambda: None)

    c = make_controller(tmp_path, make_context=unreachable)
    status = group_status(run_to_end(c))
    assert status["connect"] == "fout"
    assert all(v == "overgeslagen" for k, v in status.items() if k != "connect")


def test_failure_wins_over_warning_in_the_same_group(tmp_path):
    c = make_controller(tmp_path, make_context=mock_factory("wifi_weak", "wifi_5g_dead"))
    assert group_status(run_to_end(c))["wifi"] == "fout"


# ---------------------------------------------------------------- issue #16: opruimen vóór 'done'

def test_the_phase_stays_running_until_the_cleanup_is_finished(tmp_path):
    seen = []

    def make():
        ctx, _ = factory.mock_context([])
        c_ref = holder["c"]

        def close():
            seen.append(c_ref.state()["phase"])
            seen.append(c_ref.reset()[0])   # een nieuwe test mag nog niet kunnen tijdens het opruimen
            seen.append(c_ref.start()[0])
        return ctx, close

    holder = {}
    c = make_controller(tmp_path, make_context=make)
    holder["c"] = c
    s = run_to_end(c)
    assert seen == ["running", False, False]
    assert s["phase"] == "done"


def test_a_crash_during_cleanup_still_ends_in_done(tmp_path):
    def make():
        ctx, _ = factory.mock_context([])

        def close():
            raise RuntimeError("opruimen faalt")
        return ctx, close

    s = run_to_end(make_controller(tmp_path, make_context=make))
    assert s["phase"] == "done" and s["last"]["html"] is not None


# ---------------------------------------------------------------- issue #17 en #18: cross-site verzoeken en vreemde bodies

def test_a_post_that_is_not_json_is_refused_without_side_effects(web):
    controller, request, _ = web
    status, _ = request("POST", "/api/start", raw=b"{}", headers={"Content-Type": "text/plain"})
    assert status == 415 and controller.state()["phase"] == "idle"  # text/plain heeft geen CORS-preflight
    assert request("POST", "/api/start", raw=b"{}", headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    status, _ = request("POST", "/api/start", raw=b"{}", headers={"Content-Type": "application/json; charset=utf-8"})
    assert status == 200


def test_a_post_from_another_origin_is_refused_without_side_effects(web):
    controller, request, _ = web
    status, _ = request("POST", "/api/start", {}, headers={"Origin": "http://evil.example"})
    assert status == 403 and controller.state()["phase"] == "idle"
    assert request("POST", "/api/start", {}, headers={"Origin": "null"})[0] == 403
    assert request("POST", "/api/reset", {}, headers={"Origin": "http://127.0.0.1:1"})[0] == 403  # verkeerde poort
    assert controller.state()["phase"] == "idle"


def test_a_post_from_the_page_itself_is_accepted(web):
    controller, request, _ = web
    assert request("POST", "/api/start", {}, headers={"Origin": f"http://127.0.0.1:{request.port}"})[0] == 200
    controller.join(30)
    host = f"localhost:{request.port}"  # een browser stuurt Host en Origin altijd samen
    assert request("POST", "/api/reset", {}, host=host, headers={"Origin": f"http://{host}"})[0] == 200


@pytest.mark.parametrize("raw", [b"[]", b"null", b"3", b'"tekst"', b"true"])
def test_a_json_body_that_is_not_an_object_is_a_clean_400(web, monkeypatch, raw):
    _, request, _ = web
    monkeypatch.setattr(ui_server.subprocess, "Popen", lambda argv: pytest.fail("mag niet uitschakelen"))
    status, body = request("POST", "/api/shutdown", raw=raw)
    assert status == 400 and json.loads(body)["ok"] is False


# ---------------------------------------------------------------- afsluiten: applicatie of Pi, met of zonder TEST-CLIENT

@pytest.fixture
def exit_web(tmp_path, monkeypatch):
    """Een server met afsluiten aan; legt vast welke commando's gestart worden en of de TEST-CLIENT is uitgeschakeld."""
    from rpitest.agent.client import RpcError
    started, events = [], []
    client = {"fail": None}

    def client_power_off():
        events.append("client")
        if client["fail"]:
            raise RpcError(client["fail"])

    monkeypatch.setattr(ui_server.subprocess, "Popen", lambda argv: (events.append("server"), started.append(argv)))
    controller = make_controller(tmp_path)
    (tmp_path / "reports").mkdir()
    srv = ui_server.make_server(controller, tmp_path / "reports", "127.0.0.1", 0, allow_shutdown=True,
                                client_power_off=client_power_off)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def post(body):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("POST", "/api/shutdown", json.dumps(body), {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    yield post, started, events, client, controller, tmp_path
    srv.shutdown()
    srv.server_close()


def test_closing_only_the_application_stops_the_browser_and_the_service(exit_web):
    post, started, events, _, _, tmp_path = exit_web
    status, data = post({"confirm": True, "mode": "app"})
    assert status == 200 and data["ok"] and "applicatie wordt gesloten" in data["message"]
    wait_until(lambda: len(started) == 2)
    assert started[0][:3] == ["pkill", "-f", "--"] and "rpitest-kiosk" in started[0][-1]  # de kioskbrowser
    assert started[1] == ["systemctl", "--no-block", "stop", "rpitest-ui.service"]
    assert ["systemctl", "poweroff"] not in started and "client" not in events
    assert ui_server.exit_flag_path(tmp_path / "reports").read_text() == "1"  # kiosk.sh herstart de browser dan niet


def test_poweroff_with_the_client_shuts_the_client_down_first(exit_web):
    post, started, events, _, _, _ = exit_web
    status, data = post({"confirm": True, "mode": "poweroff", "client": True})
    assert status == 200 and "TEST-CLIENT wordt ook uitgeschakeld" in data["message"]
    wait_until(lambda: started)
    assert started == [["systemctl", "poweroff"]] and events == ["client", "server"]


def test_poweroff_without_the_client_leaves_the_client_alone(exit_web):
    post, started, events, _, _, tmp_path = exit_web
    assert post({"confirm": True, "mode": "poweroff", "client": False})[0] == 200
    wait_until(lambda: started)
    assert events == ["server"] and not ui_server.exit_flag_path(tmp_path / "reports").exists()


def test_the_default_stays_poweroff_without_the_client(exit_web):
    post, started, events, _, _, _ = exit_web
    assert post({"confirm": True})[0] == 200
    wait_until(lambda: started)
    assert started == [["systemctl", "poweroff"]] and events == ["server"]


@pytest.mark.parametrize("mode", ["app", "poweroff"])
def test_nothing_is_closed_when_the_client_cannot_be_shut_down(exit_web, mode):
    post, started, events, client, _, tmp_path = exit_web
    client["fail"] = "TEST-CLIENT niet bereikbaar: time-out"
    status, data = post({"confirm": True, "mode": mode, "client": True})
    assert status == 502 and not data["ok"] and "niet uitgeschakeld" in data["message"] and "niets afgesloten" in data["message"]
    time.sleep(0.3)
    assert started == [] and not ui_server.exit_flag_path(tmp_path / "reports").exists()


@pytest.mark.parametrize("body", [
    {"confirm": True, "mode": "reboot"}, {"confirm": True, "mode": 3}, {"confirm": True, "client": "ja"},
    {"confirm": True, "client": 1}, {"confirm": True, "mode": None},
])
def test_an_invalid_exit_request_is_refused_without_side_effects(exit_web, body):
    post, started, events, _, _, _ = exit_web
    status, _ = post(body)
    assert status == 400
    time.sleep(0.2)
    assert started == [] and events == []


@pytest.mark.parametrize("mode", ["app", "poweroff"])
def test_no_exit_while_a_test_is_running(exit_web, mode):
    post, started, events, _, controller, _ = exit_web
    gate = threading.Event()
    controller._groups = {"slow": lambda ctx: (gate.wait(30), [CheckResult("slow", Status.PASS, "ok")])[1]}
    controller.start()
    wait_until(lambda: controller.state()["phase"] == "running")
    try:
        assert post({"confirm": True, "mode": mode, "client": True})[0] == 409
    finally:
        gate.set()
        controller.join(30)
    assert started == [] and events == []


def test_the_client_option_needs_a_way_to_reach_the_client(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_server.subprocess, "Popen", lambda argv: pytest.fail("mag niets starten"))
    srv = ui_server.make_server(make_controller(tmp_path), tmp_path, "127.0.0.1", 0, allow_shutdown=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("POST", "/api/shutdown", json.dumps({"confirm": True, "client": True}),
                     {"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_failing_command_after_the_response_does_not_crash_the_handler(tmp_path, monkeypatch):
    def missing(argv):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(ui_server.subprocess, "Popen", missing)  # bv. geen systemctl bij een ontwikkelrun
    (tmp_path / "reports").mkdir()
    srv = ui_server.make_server(make_controller(tmp_path), tmp_path / "reports", "127.0.0.1", 0, allow_shutdown=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for mode in ("app", "poweroff"):
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            conn.request("POST", "/api/shutdown", json.dumps({"confirm": True, "mode": mode}),
                         {"Content-Type": "application/json"})
            assert conn.getresponse().status == 200
            conn.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_exit_flag_lives_next_to_the_reports(tmp_path):
    assert ui_server.exit_flag_path(tmp_path / "var" / "reports") == tmp_path / "var" / "kiosk-exit"
