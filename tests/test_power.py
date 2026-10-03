import json
import subprocess
import sys

import pytest

from rpitest import config
from rpitest.agent.client import LocalClient, RemoteGpioPort
from rpitest.agent.core import Agent
from rpitest.checks import power
from rpitest.context import Context
from rpitest.gpio.mock import CLIENT as GPIO_CLIENT, SERVER as GPIO_SERVER, MockWiring
from rpitest.models import Status
from rpitest.runner import run_all
from rpitest.system import mock as sysmock, parsers, stress
from rpitest.system.linux import LinuxOps, ShellResult
from rpitest.system.ops import OpsError

INFO = {"model": "Raspberry Pi 5 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}


def make_ctx(*faults):
    env = sysmock.MockEnv(faults)
    wiring = MockWiring()
    client = LocalClient(Agent(wiring.port(GPIO_CLIENT), lambda: INFO, env.ops(sysmock.CLIENT)))
    return Context(wiring.port(GPIO_SERVER), RemoteGpioPort(client), client, {}, env.ops(sysmock.SERVER))


def results(*faults):
    return {r.name: r for r in power.run(make_ctx(*faults))}


# ---------- de check met de simulatie ----------

def test_healthy_client_passes_all_power_checks():
    r = results()
    assert set(r) == {"power.sensors", "power.supply", "power.thermal", "power.cpu", "power.memory"}
    assert all(x.status is Status.PASS for x in r.values()), {n: x.summary for n, x in r.items()}


def test_undervoltage_during_load_fails_supply():
    r = results("power_undervolt")
    assert r["power.supply"].status is Status.FAIL and "onderspanning" in r["power.supply"].summary


def test_undervoltage_history_only_warns():
    assert results("power_undervolt_history")["power.supply"].status is Status.WARN


def test_very_hot_fails_and_warm_warns():
    assert results("power_hot")["power.thermal"].status is Status.FAIL
    assert results("power_warm")["power.thermal"].status is Status.WARN
    assert results("power_throttle")["power.thermal"].status is Status.WARN


def test_cpu_errors_and_missing_core_fail():
    assert results("power_cpu_error")["power.cpu"].status is Status.FAIL
    r = results("power_core_missing")["power.cpu"]
    assert r.status is Status.FAIL and "3 van 4" in r.summary


def test_memory_errors_fail():
    assert results("power_ram_error")["power.memory"].status is Status.FAIL


def test_missing_temperature_sensor_fails():
    assert results("power_no_sensor")["power.sensors"].status is Status.FAIL


def test_power_is_part_of_the_full_run_and_healthy_run_passes():
    report = run_all(make_ctx())
    assert report.overall == "PASS"
    assert "power.thermal" in {r.name for r in report.results}


def test_stress_is_started_with_configured_duration_and_always_stopped_on_failure():
    ctx = make_ctx()
    calls = []
    real_call = ctx.client.call

    def spy(method, **kw):
        calls.append((method, kw))
        if method == "stress_poll":
            raise OpsError("kapot")
        return real_call(method, **kw)

    ctx.client.call = spy
    out = power.run(ctx)
    assert out[0].status is Status.FAIL
    assert ("stress_start", {"seconds": config.STRESS_SECONDS, "ram_mb": config.STRESS_RAM_MB}) in calls
    assert any(m == "stress_stop" for m, _ in calls)


def test_agent_validates_stress_parameters():
    ctx = make_ctx()
    for params in ({"seconds": 1, "ram_mb": 64}, {"seconds": 60, "ram_mb": 100000}, {"seconds": "60", "ram_mb": 64}):
        with pytest.raises(Exception, match="Error"):
            ctx.client.call("stress_start", **params)


# ---------- beoordeling zonder simulatie ----------

def sample(temp=45.0, throttled=0, freq=2400.0, volts=None, online=4):
    return {"temp_c": temp, "freq_mhz": freq, "freq_max_mhz": 2400.0, "throttled": throttled,
            "volts": volts or {}, "cores_online": online, "cores_present": 4}


def test_throttle_caused_by_undervoltage_is_not_blamed_on_temperature():
    samples = [sample(), sample(temp=55, throttled=0x1, freq=1000.0)]
    assert power.check_thermal(samples).status is Status.PASS
    assert power.check_supply(samples).status is Status.FAIL


def test_low_input_voltage_warns_even_without_flag():
    samples = [sample(), sample(volts={"EXT5V_V": 4.6})]
    assert power.check_supply(samples).status is Status.WARN


def test_slow_core_warns():
    result = {"cpu": [{"rounds": 100, "bad": 0}] * 3 + [{"rounds": 20, "bad": 0}], "ram": None, "errors": []}
    assert power.check_cpu([sample()], result).status is Status.WARN
    assert power.check_memory(result).status is Status.WARN  # RAM-test niet uitgevoerd


def test_worker_crash_is_reported_as_failure():
    result = {"cpu": [{"rounds": 100, "bad": 0}], "ram": None, "errors": ["ram-worker gaf geen resultaat"]}
    assert power.check_cpu([sample()], result).status is Status.FAIL


def test_missing_vcgencmd_warns_instead_of_failing():
    samples = [dict(sample(), throttled=None), dict(sample(), throttled=None)]
    assert power.check_sensors(samples).status is Status.WARN


# ---------- parsers ----------

def test_decode_throttled():
    flags = parsers.decode_throttled(0x50005)
    assert flags["undervoltage_now"] and flags["throttled_now"] and flags["undervoltage_occurred"]
    assert not flags["soft_temp_limit_now"]
    assert not any(parsers.decode_throttled(None).values())


def test_parse_throttled_and_cpu_list():
    assert parsers.parse_throttled("throttled=0x0\n") == 0
    assert parsers.parse_throttled("error") is None
    assert parsers.parse_cpu_list("0-3") == 4 and parsers.parse_cpu_list("0,2-3") == 3


# ---------- LinuxOps.power_sample met nagebootste sysfs ----------

class FakeShell:
    def __init__(self, answers):
        self.answers = answers

    def run(self, argv, timeout=30):
        return self.answers.get(argv[1], ShellResult(127, "", "niet gevonden"))


def test_power_sample_reads_sysfs_and_vcgencmd(tmp_path):
    def put(rel, text):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    put("sys/class/thermal/thermal_zone0/temp", "52300\n")
    put("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "2400000\n")
    put("sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "2400000\n")
    put("sys/devices/system/cpu/online", "0-3\n")
    put("sys/devices/system/cpu/present", "0-3\n")
    shell = FakeShell({"get_throttled": ShellResult(0, "throttled=0x50000\n"),
                       "pmic_read_adc": ShellResult(0, " EXT5V_V volt(24)=4.94246000V\n")})
    s = LinuxOps(shell, tmp_path).power_sample()
    assert s["temp_c"] == 52.3 and s["freq_mhz"] == 2400.0 and s["cores_online"] == 4
    assert s["throttled"] == 0x50000 and s["volts"] == {"EXT5V_V": 4.94246}


def test_power_sample_without_sensors_gives_nones(tmp_path):
    s = LinuxOps(FakeShell({}), tmp_path).power_sample()
    assert s["temp_c"] is None and s["throttled"] is None and s["volts"] == {}


# ---------- de echte werkers ----------

def test_cpu_expected_constant_matches_the_algorithm():
    assert stress.cpu_round() == stress.CPU_EXPECTED  # beschermt tegen een verkeerd gekopieerde constante


def test_cpu_worker_counts_bad_results():
    ok = stress.cpu_worker(0, round_fn=lambda: stress.CPU_EXPECTED)
    bad = stress.cpu_worker(0, round_fn=lambda: b"fout")
    assert ok == {"role": "cpu", "rounds": 1, "bad": 0}
    assert bad["bad"] == 1


def test_ram_pass_detects_a_flipped_bit():
    buf = bytearray(2 * stress.CHUNK)
    assert stress.ram_pass(buf) == 0

    class Flipping(bytearray):  # simuleert een cel die een bit laat vallen na het schrijven
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if isinstance(key, slice) and key.start == 0 and value[:1] == b"\xaa":
                super().__setitem__(5, 0x00)

    assert stress.ram_pass(Flipping(2 * stress.CHUNK)) >= 1


def test_ram_worker_runs_at_least_one_pass():
    result = stress.ram_worker(0, mb=2)
    assert result["passes"] == 1 and result["bad"] == 0 and result["mb"] == 2


def test_worker_process_prints_one_json_line():
    out = subprocess.run([sys.executable, "-m", "rpitest.system.stress", "cpu", "--seconds", "0"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1])["bad"] == 0


def test_linuxops_stress_lifecycle_with_real_worker_processes(tmp_path):
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/meminfo").write_text("MemAvailable:      204800 kB\n")  # 200 MB -> RAM-test van 16 MB
    ops = LinuxOps(root=tmp_path)
    assert ops.stress_poll() == {"running": False, "elapsed": 0.0}
    with pytest.raises(OpsError, match="geen belastingstest"):
        ops.stress_result()
    ops.stress_start(1, 16)
    try:
        with pytest.raises(OpsError, match="loopt nog"):
            ops.stress_result()
        import time
        deadline = time.monotonic() + 60
        while ops.stress_poll()["running"] and time.monotonic() < deadline:
            time.sleep(0.2)
        result = ops.stress_result()
    finally:
        ops.stress_stop()
    assert result["errors"] == []
    assert len(result["cpu"]) >= 1 and all(w["bad"] == 0 and w["rounds"] >= 1 for w in result["cpu"])
    assert result["ram"]["mb"] == 16 and result["ram"]["bad"] == 0


def test_linuxops_stress_skips_ram_when_memory_is_unknown(tmp_path):
    ops = LinuxOps(root=tmp_path)  # geen /proc/meminfo
    ops.stress_start(1, 256)
    try:
        import time
        deadline = time.monotonic() + 60
        while ops.stress_poll()["running"] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert ops.stress_result()["ram"] is None
    finally:
        ops.stress_stop()
