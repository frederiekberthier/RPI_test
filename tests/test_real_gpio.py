import pytest
from fake_gpiod import Bias, Direction, FakeSystem, Value

from rpitest.gpio import real
from rpitest.gpio.ports import EXTERNAL_PULLUP, GND_HEADER_PINS, HEADER_PIN, PINS, POWER_HEADER_PINS, Pull
from rpitest.sysinfo import pi_info

PI5_CHIPS = {
    "/dev/gpiochip0": ("pinctrl-rp1", 54),
    "/dev/gpiochip10": ("gpio-brcmstb@107d508500", 32),
}


@pytest.fixture
def system(monkeypatch):
    system = FakeSystem(dict(PI5_CHIPS))
    monkeypatch.setattr(real.glob, "glob", lambda pattern: sorted(system.chips))
    return system


def test_finds_header_chip_by_label(system):
    assert real.find_header_chip(system.module()) == "/dev/gpiochip0"


def test_ignores_chips_that_are_not_the_header(system):
    system.chips = {"/dev/gpiochip0": ("gpio-brcmstb@107d508500", 32), "/dev/gpiochip4": ("pinctrl-rp1", 54)}
    assert real.find_header_chip(system.module()) == "/dev/gpiochip4"


def test_no_header_chip_gives_helpful_error(system):
    system.chips = {"/dev/gpiochip0": ("iets-anders", 8)}
    with pytest.raises(RuntimeError, match="iets-anders"):
        real.find_header_chip(system.module())


def test_all_pins_requested_as_inputs_without_pull(system):
    real.GpiodPort(gpiod=system.module())
    cfg = system.requests[0].config
    assert set(cfg) == set(PINS)
    assert all(s.direction is Direction.INPUT and s.bias is Bias.DISABLED for s in cfg.values())


def test_set_input_and_read(system):
    port = real.GpiodPort(gpiod=system.module())
    port.set_input(PINS, Pull.UP)
    assert set(port.read(PINS).values()) == {1}
    port.set_input([5], Pull.DOWN)
    values = port.read(PINS)
    assert values[5] == 0 and values[6] == 1


def test_drive_changes_only_that_pin_but_reconfigures_everything(system):
    port = real.GpiodPort(gpiod=system.module())
    request = system.requests[0]
    port.set_input(PINS, Pull.DOWN)
    port.drive(7, 1)
    assert len(request.config) == len(PINS)  # altijd volledige configuratie
    assert request.config[7].direction is Direction.OUTPUT and request.config[7].output_value is Value.ACTIVE
    assert request.config[8].bias is Bias.PULL_DOWN
    assert port.read([7, 8]) == {7: 1, 8: 0}
    port.set_input([7], Pull.DOWN)  # loslaten
    assert request.config[7].direction is Direction.INPUT


def test_rejects_bad_arguments(system):
    port = real.GpiodPort(gpiod=system.module())
    with pytest.raises(ValueError):
        port.drive(5, 2)
    with pytest.raises(ValueError):
        port.set_input([5], "sideways")
    with pytest.raises(ValueError, match="niet beheerd"):
        port.read([0])  # GPIO0/1 zijn gereserveerd


def test_close_releases_lines_once(system):
    with real.GpiodPort(gpiod=system.module()) as port:
        request = system.requests[0]
    assert request.released
    port.close()  # tweede keer is onschuldig


def test_busy_lines_are_named_in_the_error(system):
    system.busy = {2, 3}  # bv. I2C-overlay claimt GPIO2/3
    with pytest.raises(RuntimeError, match="2, 3"):
        real.GpiodPort(gpiod=system.module())


def test_header_table_is_consistent():
    assert set(HEADER_PIN) == set(PINS)
    assert len(set(HEADER_PIN.values())) == len(PINS)  # elke GPIO een eigen fysieke pin
    assert not set(HEADER_PIN.values()) & (set(POWER_HEADER_PINS) | set(GND_HEADER_PINS))
    assert all(1 <= p <= 40 for p in HEADER_PIN.values())
    assert {3, 5} == {HEADER_PIN[p] for p in EXTERNAL_PULLUP}  # I2C-pinnen


def test_pi_info_from_fake_proc(tmp_path):
    (tmp_path / "proc" / "device-tree").mkdir(parents=True)
    (tmp_path / "proc" / "device-tree" / "model").write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
    (tmp_path / "proc" / "cpuinfo").write_text("processor\t: 0\nRevision\t: d04170\nSerial\t\t: 10000000abcdef01\n")
    (tmp_path / "proc" / "meminfo").write_text("MemTotal:        8210000 kB\n")
    info = pi_info(tmp_path)
    assert info["model"] == "Raspberry Pi 5 Model B Rev 1.0"
    assert info["serial"] == "10000000abcdef01"
    assert info["revision"] == "d04170"
    assert info["ram_mb"] == 8192  # afgerond naar nominaal geheugen


def test_pi_info_survives_missing_files(tmp_path):
    assert pi_info(tmp_path)["model"] == "onbekend"


# ---------------------------------------------------------------- issue #10: de juiste foutmelding

def failing_module(system, errno_value, text):
    mod = system.module()

    def fail(path, consumer=None, config=None):
        raise OSError(errno_value, text)

    mod.request_lines = fail
    return mod


def test_permission_errors_are_not_reported_as_busy_pins(system):
    import errno
    mod = failing_module(system, errno.EACCES, "Permission denied")
    with pytest.raises(RuntimeError) as exc:
        real.GpiodPort("/dev/gpiochip0", gpiod=mod)
    message = str(exc.value)
    assert "geen toegang" in message and "/dev/gpiochip0" in message and "sudo" in message
    assert "in gebruik" not in message and "2, 3" not in message


def test_a_missing_chip_is_reported_as_missing(system):
    import errno
    mod = failing_module(system, errno.ENOENT, "No such file or directory")
    with pytest.raises(RuntimeError, match="bestaat niet") as exc:
        real.GpiodPort("/dev/gpiochip9", gpiod=mod)
    assert "--list-chips" in str(exc.value) and "in gebruik" not in str(exc.value)


def test_other_errors_keep_the_original_error_text(system):
    import errno
    mod = failing_module(system, errno.EIO, "Input/output error")
    with pytest.raises(RuntimeError, match="Input/output error") as exc:
        real.GpiodPort("/dev/gpiochip0", gpiod=mod)
    assert "in gebruik" not in str(exc.value)


def test_only_busy_pins_are_named_when_some_pins_are_busy(system):
    system.busy = {14, 15}
    with pytest.raises(RuntimeError) as exc:
        real.GpiodPort(gpiod=system.module())
    message = str(exc.value)
    assert "14, 15" in message and "2," not in message
