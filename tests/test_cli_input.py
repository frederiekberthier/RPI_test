"""Invoer van de opdrachtregel: --fault en --usb-fixture geven duidelijke meldingen in plaats van een traceback."""

import json

import pytest

from rpitest import __main__ as cli
from rpitest import factory
from rpitest.gpio.mock import CLIENT, SERVER, MockWiring
from rpitest.ui import __main__ as ui_cli


# ---------------------------------------------------------------- issue #36: --fault

@pytest.mark.parametrize("kind,args,fragment", [
    ("onzin", (), "onbekende fout"),
    ("stuck_low", (), "verwacht <zijde>:<pin>"),
    ("stuck_low", (CLIENT,), "verwacht <zijde>:<pin>"),
    ("stuck_low", ("X", "5"), "onbekende zijde"),
    ("stuck_low", (CLIENT, "abc"), "geen pinnummer"),
    ("stuck_low", (CLIENT, "99"), "GPIO99 bestaat niet"),
    ("stuck_high", (SERVER, "1"), "GPIO1 bestaat niet"),
    ("bridge", (CLIENT, "5"), "verwacht <zijde>:<pin>:<pin>"),
    ("bridge", (CLIENT, "5", "5"), "twee verschillende pinnen"),
    ("open", (), "verwacht <pin>"),
    ("open", ("28",), "GPIO28 bestaat niet"),
])
def test_a_bad_gpio_fault_is_a_clear_value_error(kind, args, fragment):
    with pytest.raises(ValueError, match=fragment):
        MockWiring().add_fault(kind, *args)


def test_valid_gpio_faults_are_still_accepted():
    wiring = MockWiring()
    for kind, args in (("stuck_low", (CLIENT, "5")), ("stuck_high", (SERVER, 9)), ("bridge", (CLIENT, 5, 6)), ("open", ("7",))):
        wiring.add_fault(kind, *args)


@pytest.mark.parametrize("spec,fragment", [
    ("stuck_low:X:5", "--fault stuck_low:X:5: onbekende zijde"),
    ("stuck_low", "verwacht <zijde>:<pin>"),
    ("stuck_low:C:abc", "geen pinnummer"),
    ("no_wifi:5", "heeft geen argumenten"),
    ("verzonnen", "onbekende fout"),
])
def test_split_faults_names_the_offending_option(spec, fragment):
    with pytest.raises(ValueError, match=fragment):
        factory.split_faults([spec])


@pytest.mark.parametrize("main,extra", [(cli.main, []), (ui_cli.main, ["--port", "0"])])
@pytest.mark.parametrize("spec", ["stuck_low:X:5", "stuck_low", "stuck_low:C:abc"])
def test_both_command_lines_report_a_bad_fault_and_exit_2(main, extra, spec, capsys, tmp_path):
    assert main(["--mock", "--fault", spec, "--out", str(tmp_path), *extra]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Fout: ") and spec in err and "Traceback" not in err


# ---------------------------------------------------------------- issue #37: --usb-fixture

def write(tmp_path, content):
    path = tmp_path / "fixture.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


GOOD = {"label": "SLOT1", "name": "USB3 poort 1", "min_speed_mbit": 5000, "min_read_mb_s": 60}


def test_a_valid_fixture_file_is_loaded(tmp_path):
    assert factory.load_usb_slots(write(tmp_path, [GOOD])) == [GOOD]
    assert factory.load_usb_slots(None) is None
    minimal = {"label": "A", "min_speed_mbit": 480, "min_read_mb_s": 10.5}  # name is optioneel
    assert factory.load_usb_slots(write(tmp_path, [minimal])) == [minimal]


@pytest.mark.parametrize("content,fragment", [
    ([{"label": "SLOT1"}], "'min_speed_mbit' ontbreekt"),
    ([{"label": "SLOT1", "min_speed_mbit": 480}], "'min_read_mb_s' ontbreekt"),
    ([{**GOOD, "min_read_mb_s": "snel"}], "'min_read_mb_s' ontbreekt of is geen getal"),
    ([{**GOOD, "min_speed_mbit": True}], "'min_speed_mbit'"),
    ([{**GOOD, "min_speed_mbit": -1}], "'min_speed_mbit'"),
    ([{"min_speed_mbit": 1, "min_read_mb_s": 1}], "'label' ontbreekt"),
    ([GOOD, GOOD], "twee keer voor"),
    ([{**GOOD, "name": 3}], "'name' moet tekst zijn"),
    ([], "niet-lege lijst"),
    ({"label": "SLOT1"}, "niet-lege lijst"),
    (["SLOT1"], "verwacht een object"),
    ("{dit is geen json", "geen geldige JSON"),
])
def test_an_invalid_fixture_file_is_reported_with_the_problem(tmp_path, content, fragment):
    with pytest.raises(ValueError, match=fragment) as exc:
        factory.load_usb_slots(write(tmp_path, content))
    assert "fixture.json" in str(exc.value)


def test_a_missing_fixture_file_is_reported(tmp_path):
    with pytest.raises(ValueError, match="niet te lezen"):
        factory.load_usb_slots(tmp_path / "bestaat-niet.json")


@pytest.mark.parametrize("main,extra", [(cli.main, []), (ui_cli.main, ["--port", "0"])])
def test_both_command_lines_report_a_bad_fixture_and_exit_2(main, extra, capsys, tmp_path):
    path = write(tmp_path, [{"label": "SLOT1"}])
    assert main(["--mock", "--usb-fixture", str(path), "--out", str(tmp_path), *extra]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Fout: ") and "min_speed_mbit" in err and "Traceback" not in err
