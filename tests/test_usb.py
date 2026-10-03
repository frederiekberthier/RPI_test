import os

import pytest

from rpitest import usbtools
from rpitest.agent.client import LocalClient, RemoteGpioPort
from rpitest.agent.core import Agent
from rpitest.context import Context
from rpitest.gpio.mock import CLIENT as GPIO_CLIENT
from rpitest.gpio.mock import SERVER as GPIO_SERVER
from rpitest.gpio.mock import MockWiring
from rpitest.models import Status
from rpitest.runner import run_all
from rpitest.system import mock as sysmock
from rpitest.system import parsers, storage
from rpitest.system.linux import LinuxOps, is_usb_device_name, usb_block_devices
from rpitest.system.ops import OpsError

INFO = {"model": "Raspberry Pi 5 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}
MB = 1 << 20


# ---------- opslag: veiligheid en dataintegriteit (op een gewoon bestand) ----------

def make_stick(tmp_path, label="SLOT1", size_mb=64, name="stick.img"):
    path = tmp_path / name
    with open(path, "wb") as f:
        f.truncate(size_mb * MB)
    if label:
        storage.write_label(str(path), label, allow_file=True)
    return str(path)


def test_header_roundtrip(tmp_path):
    assert storage.read_label(make_stick(tmp_path, "SLOT3")) == "SLOT3"


def test_label_validation():
    for bad in ("", "x" * 33, "tab\there", "één"):
        with pytest.raises(ValueError):
            storage.make_header(bad)


def test_storage_test_passes_and_leaves_header_and_start_untouched(tmp_path):
    path = make_stick(tmp_path)
    before = open(path, "rb").read(16 * MB)
    result = storage.run_storage_test(path, size_mb=4, direct=False, allow_file=True)
    assert result["mismatching_chunks"] == 0 and result["mb"] == 4
    assert open(path, "rb").read(16 * MB) == before  # niets voor het testgebied aangeraakt
    assert storage.read_label(path) == "SLOT1"


def test_storage_test_refuses_device_without_header(tmp_path):
    path = make_stick(tmp_path, label=None)
    with open(path, "r+b") as f:
        f.write(b"studentdata" * 100)
    snapshot = open(path, "rb").read()
    with pytest.raises(OpsError, match="geen RPITEST-fixtureheader"):
        storage.run_storage_test(path, size_mb=2, direct=False, allow_file=True)
    assert open(path, "rb").read() == snapshot  # niet geschreven


def test_storage_test_refuses_too_small_device(tmp_path):
    path = make_stick(tmp_path, size_mb=20)
    with pytest.raises(OpsError, match="te klein"):
        storage.run_storage_test(path, size_mb=8, direct=False, allow_file=True)


def test_storage_test_detects_corruption(tmp_path, monkeypatch):
    path = make_stick(tmp_path)
    real_fsync = os.fsync

    def corrupting_fsync(fd):
        real_fsync(fd)
        os.lseek(fd, 16 * MB + 100, os.SEEK_SET)  # beschadig drie bytes in het testgebied
        os.write(fd, b"\xff\x00\xff")

    monkeypatch.setattr(storage.os, "fsync", corrupting_fsync)
    assert storage.run_storage_test(path, size_mb=4, direct=False, allow_file=True)["mismatching_chunks"] == 1


# ---------- sysfs en kernelberichten ----------

def test_usb_block_devices_uses_resolved_path(tmp_path, monkeypatch):
    (tmp_path / "sys/block/sda").mkdir(parents=True)
    (tmp_path / "sys/block/mmcblk0").mkdir()
    syspaths = {
        "sda": "/sys/devices/platform/axi/usb2/2-1/2-1.1/2-1.1:1.0/host0/target0:0:0/0:0:0:0/block/sda",
        "mmcblk0": "/sys/devices/platform/axi/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0",
    }
    monkeypatch.setattr("rpitest.system.linux.os.path.realpath", lambda p: syspaths[os.path.basename(p)])
    assert usb_block_devices(tmp_path) == {"2-1.1": "sda"}  # de SD-kaart hoort er niet bij


def make_usb_sysfs(tmp_path):
    base = tmp_path / "sys/bus/usb/devices"
    for name, files in {
        "usb1": {"idVendor": "1d6b"},  # root hub: overslaan
        "1-1": {"idVendor": "2109", "idProduct": "3431", "speed": "480", "bDeviceClass": "09"},
        "1-1.3": {"idVendor": "0781", "idProduct": "5581", "manufacturer": "SanDisk", "product": "Ultra",
                  "serial": "ABC", "speed": "5000", "bDeviceClass": "00"},
    }.items():
        (base / name).mkdir(parents=True)
        for fname, value in files.items():
            (base / name / fname).write_text(value + "\n")
    return tmp_path


def test_usb_scan_reads_sysfs_and_skips_hubs_interfaces_and_roots(tmp_path):
    devices = LinuxOps(root=make_usb_sysfs(tmp_path)).usb_scan()
    assert [d["path"] for d in devices] == ["1-1", "1-1.3"]
    assert devices[0]["is_hub"] and not devices[1]["is_hub"]
    assert devices[1]["speed_mbit"] == 5000.0 and devices[1]["serial"] == "ABC" and devices[1]["block"] is None


def test_device_name_filter():
    # mappen met ':' kunnen we op Windows niet nabootsen, dus de naamfilter wordt los getest
    assert is_usb_device_name("1-1.3") and is_usb_device_name("2-1")
    assert not is_usb_device_name("usb1") and not is_usb_device_name("1-1.3:1.0")


def test_storage_test_only_allows_usb_sd_devices(tmp_path, monkeypatch):
    ops = LinuxOps(root=tmp_path)
    for bad in ("mmcblk0", "sda1", "../sda", "nvme0n1", "sda; rm"):
        with pytest.raises(OpsError, match="toegestaan"):
            ops.usb_storage_test(bad, 4)
    monkeypatch.setattr("rpitest.system.linux.os.path.realpath", lambda p: "/sys/devices/pci/ata1/host0/block/sda")
    with pytest.raises(OpsError, match="geen USB-apparaat"):  # een interne SATA-schijf
        ops.usb_storage_test("sda", 4)


# ---------- usbtools: voorbereiden van sticks ----------

USB_SYSPATH = "/sys/devices/platform/usb2/2-1/2-1.1/2-1.1:1.0/host0/target0:0:0/0:0:0:0/block/sdb"


def sys_with_size(tmp_path, sectors):
    (tmp_path / "sys/block/sdb").mkdir(parents=True)
    (tmp_path / "sys/block/sdb/size").write_text(f"{sectors}\n")
    return tmp_path


def validate(tmp_path, device="/dev/sdb", label="SLOT1", sectors=15_000_000, syspath=USB_SYSPATH, mounts=""):
    return usbtools.validate_prepare_target(device, label, sys_with_size(tmp_path, sectors),
                                            lambda p: syspath, mounts)


def test_prepare_accepts_a_small_usb_stick(tmp_path):
    assert validate(tmp_path) is None


@pytest.mark.parametrize("kwargs,expected", [
    ({"device": "/dev/sdb1"}, "hele schijven"),
    ({"device": "/dev/mmcblk0"}, "hele schijven"),
    ({"label": ""}, "label"),
    ({"syspath": "/sys/devices/pci/ata1/host0/block/sdb"}, "geen USB"),
    ({"sectors": 2_000_000_000}, "lijkt geen teststick"),
    ({"mounts": "/dev/sdb1 /media/student vfat rw 0 0\n"}, "gekoppeld"),
])
def test_prepare_refuses(tmp_path, kwargs, expected):
    assert expected in validate(tmp_path, **kwargs)


def test_prepare_without_yes_does_not_write(monkeypatch, capsys):
    monkeypatch.setattr(usbtools, "validate_prepare_target", lambda *a, **k: None)
    monkeypatch.setattr(usbtools.storage, "write_label", lambda *a: pytest.fail("mag niet schrijven"))
    assert usbtools.main(["prepare", "/dev/sdb", "--label", "SLOT1"]) == 1
    assert "--yes" in capsys.readouterr().out


# ---------- de check zelf, met de simulatie ----------

def make_ctx(*faults, slots=None):
    env = sysmock.MockEnv(faults)
    wiring = MockWiring()
    client = LocalClient(Agent(wiring.port(GPIO_CLIENT), lambda: INFO, env.ops(sysmock.CLIENT)))
    return Context(wiring.port(GPIO_SERVER), RemoteGpioPort(client), client, {}, env.ops(sysmock.SERVER), slots)


def usb_results(*faults, **kwargs):
    return {r.name: r for r in run_all(make_ctx(*faults, **kwargs)).results if r.name.startswith("usb")}


def test_healthy_fixture_passes():
    results = usb_results()
    assert set(results) == {"usb.SLOT1", "usb.SLOT2", "usb.SLOT3", "usb.SLOT4", "usb.kernel"}
    assert all(r.status is Status.PASS for r in results.values()), {n: r.summary for n, r in results.items()}


def test_dead_port_is_named():
    r = usb_results("usb_slot3_dead")
    assert r["usb.SLOT3"].status is Status.FAIL and "USB2 poort 1" in r["usb.SLOT3"].summary
    assert r["usb.SLOT1"].status is Status.PASS


def test_usb3_port_falling_back_to_usb2_fails():
    r = usb_results("usb_slot1_usb2")
    assert r["usb.SLOT1"].status is Status.FAIL and "480" in r["usb.SLOT1"].summary


def test_usb2_fallback_on_a_usb2_port_is_not_a_failure():
    assert usb_results("usb_slot3_usb2")["usb.SLOT3"].status is Status.PASS


def test_data_corruption_fails():
    r = usb_results("usb_slot2_corrupt")["usb.SLOT2"]
    assert r.status is Status.FAIL and "dataverlies" in r.summary


def test_slow_port_only_warns():
    assert usb_results("usb_slot4_slow")["usb.SLOT4"].status is Status.WARN


def test_no_sticks_gives_one_clear_failure():
    r = usb_results("usb_no_sticks")
    assert list(r) == ["usb.fixture"] and r["usb.fixture"].status is Status.FAIL


def test_kernel_overcurrent_and_disconnect_fail():
    assert usb_results("usb_overcurrent")["usb.kernel"].status is Status.FAIL
    assert usb_results("usb_disconnect")["usb.kernel"].status is Status.FAIL


def test_custom_fixture_with_only_two_slots():
    slots = [{"label": "SLOT1", "min_speed_mbit": 5000, "min_read_mb_s": 60},
             {"label": "SLOT2", "min_speed_mbit": 5000, "min_read_mb_s": 60}]
    assert set(usb_results(slots=slots)) == {"usb.SLOT1", "usb.SLOT2", "usb.kernel"}


def test_kernel_event_timing_boot_vs_test():
    from rpitest.checks.usb import check_kernel

    class FakeClient:
        def __init__(self, events):
            self.events = events

        def call(self, method, **kw):
            return self.events

    def status(events):
        return check_kernel(Context(None, None, FakeClient(events), {}), 100.0).status

    reset = {"category": "reset", "text": "x"}
    assert status([{**reset, "ts": 5.0}]) is Status.PASS  # resets bij het opstarten zijn normaal
    assert status([{**reset, "ts": 150.0}]) is Status.WARN
    assert status([{"category": "enumerate", "text": "x", "ts": 5.0}]) is Status.FAIL  # bij opstarten wel fout
    assert status([{"category": "disconnect", "text": "x", "ts": 5.0}]) is Status.PASS


def test_agent_validates_block_and_size():
    ctx = make_ctx()
    for params in ({"block": "mmcblk0", "size_mb": 4}, {"block": "sda", "size_mb": 100000},
                   {"block": "sda; reboot", "size_mb": 4}):
        with pytest.raises(Exception, match="Error"):
            ctx.client.call("usb_storage_test", **params)


def test_parse_usb_events_ignores_normal_messages():
    text = ("[  1.0] usb 1-1.4: new high-speed USB device number 7 using xhci_hcd\n"
            "[  2.0] usb 1-1.3: USB disconnect, device number 4\n")
    assert [e["category"] for e in parsers.parse_usb_events(text)] == ["disconnect"]


# ---------------------------------------------------------------- issue #8: snelheid zonder rekentijd

def test_reported_speeds_do_not_include_hashing_time(tmp_path, monkeypatch):
    import hashlib
    import time

    real_sha256 = hashlib.sha256

    def slow_sha256(data=b""):
        # actief wachten: conftest maakt time.sleep een no-op. Met het hashen in de meting blijft de snelheid onder 10 MB/s.
        end = time.perf_counter() + 0.1
        while time.perf_counter() < end:
            pass
        return real_sha256(data)

    monkeypatch.setattr(storage.hashlib, "sha256", slow_sha256)
    result = storage.run_storage_test(make_stick(tmp_path), size_mb=4, direct=False, allow_file=True)
    assert result["read_mb_s"] > 30 and result["write_mb_s"] > 30, result
    assert result["mismatching_chunks"] == 0


# ---------------------------------------------------------------- issue #9: veilig schrijven op een blokapparaat

def fake_block(monkeypatch, rdev=0):
    """Laat storage een gewoon bestand als blokapparaat beschouwen (en leg vast hoe het geopend wordt)."""
    monkeypatch.setattr(storage, "_kind", lambda path: ("block", rdev))


def test_a_regular_file_is_refused_by_default(tmp_path):
    path = make_stick(tmp_path)
    before = open(path, "rb").read(16 * MB + 100)
    with pytest.raises(OpsError, match="geen blokapparaat"):
        storage.run_storage_test(path, size_mb=2, direct=False)
    with pytest.raises(OpsError, match="geen blokapparaat"):
        storage.write_label(path, "SLOT2")
    assert open(path, "rb").read(16 * MB + 100) == before


def test_block_devices_are_opened_exclusively(tmp_path, monkeypatch):
    import errno
    fake_block(monkeypatch)
    seen = {}

    def refuse(path, flags, *a):
        seen["flags"] = flags
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(storage.os, "open", refuse)
    with pytest.raises(OpsError, match="in gebruik"):
        storage.run_storage_test(make_stick(tmp_path), size_mb=2, direct=False)
    assert seen["flags"] & os.O_EXCL  # Linux weigert dan een gemount of anderszins geclaimd apparaat
    seen.clear()
    with pytest.raises(OpsError, match="in gebruik"):
        storage.write_label("/dev/sdx", "SLOT1")
    assert seen["flags"] & os.O_EXCL


def test_the_header_is_read_from_the_same_descriptor_that_is_written(tmp_path, monkeypatch):
    path = make_stick(tmp_path)
    monkeypatch.setattr(storage, "read_label", lambda p: pytest.fail("aparte open voor de header-controle"))
    assert storage.run_storage_test(path, size_mb=2, direct=False, allow_file=True)["mismatching_chunks"] == 0


def test_a_device_that_was_swapped_between_check_and_open_is_refused(tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace

    path = make_stick(tmp_path)
    fake_block(monkeypatch, rdev=111)  # bij de eerste controle was dit apparaat 111
    monkeypatch.setattr(storage.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=222))
    monkeypatch.setattr(storage, "_flags", lambda direct, exclusive: os.O_RDWR | getattr(os, "O_BINARY", 0))
    with pytest.raises(OpsError, match="vervangen"):
        storage.run_storage_test(path, size_mb=2, direct=False)


def test_a_device_without_header_is_refused_without_writing(tmp_path):
    path = make_stick(tmp_path, label=None)
    snapshot = open(path, "rb").read()
    with pytest.raises(OpsError, match="geen RPITEST-fixtureheader"):
        storage.run_storage_test(path, size_mb=2, direct=False, allow_file=True)
    assert open(path, "rb").read() == snapshot


def test_a_mounted_stick_is_refused(tmp_path, monkeypatch):
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/mounts").write_text("/dev/sda1 /media/student vfat rw 0 0\n/dev/sdb /mnt ext4 rw 0 0\n")
    monkeypatch.setattr("rpitest.system.linux.os.path.realpath",
                        lambda p: "/sys/devices/platform/usb2/2-1/2-1.1/2-1.1:1.0/host0/target0:0:0/0:0:0:0/block/sda")
    ops = LinuxOps(root=tmp_path)
    with pytest.raises(OpsError, match="gekoppeld"):
        ops.usb_storage_test("sda", 4)
    assert storage.is_mounted("sda", "/dev/sda1 /x vfat rw 0 0\n")
    assert storage.is_mounted("sda", "/dev/sda /x ext4 rw 0 0\n")
    assert not storage.is_mounted("sda", "/dev/sdaa1 /x vfat rw 0 0\n/dev/sdb1 /y vfat rw 0 0\n")
