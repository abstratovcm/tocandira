import pytest

from tocandira.uhp import NOKAMUTE, REFERENCE, PlayerSpec


def test_parse_depth_defaults():
    spec = PlayerSpec.parse("depth=4")
    assert spec.cmd == NOKAMUTE
    assert spec.depth == 4
    assert spec.seconds is None
    assert spec.options == {"NumThreads": "1"}
    assert spec.name == "nokamute d4"
    assert spec.limit_args() == "depth 4"


def test_parse_seconds_and_options():
    spec = PlayerSpec.parse("seconds=1.5, Aggression=5, NumThreads=4")
    assert spec.options == {"Aggression": "5", "NumThreads": "4"}
    assert spec.limit_args() == "seconds 1.5"
    assert spec.name == "nokamute 1.5s Aggression=5"


def test_parse_reference_shorthand():
    spec = PlayerSpec.parse("cmd=ref,depth=2")
    assert spec.cmd == REFERENCE
    assert spec.name == "nokamute-1.0.3 d2"


def test_foreign_engine_uses_uhp_time_format():
    spec = PlayerSpec.parse("cmd=/opt/mzinga/MzingaEngine,seconds=90")
    assert not spec.is_nokamute
    assert spec.limit_args() == "time 00:01:30"
    assert PlayerSpec.parse("cmd=/opt/x,seconds=0.4").limit_args() == "time 00:00:01"


def test_parse_requires_a_limit():
    with pytest.raises(ValueError, match="depth= or seconds="):
        PlayerSpec.parse("Aggression=5")


def test_explicit_name_wins():
    assert PlayerSpec.parse("depth=1,name=foo").name == "foo"


def test_engine_arguments_do_not_hide_the_binary():
    spec = PlayerSpec.parse("cmd=/x/nokamute --nnue /y/weights.bin,seconds=1")
    assert spec.is_nokamute
    assert spec.name == "nokamute 1.0s"
    assert spec.limit_args() == "seconds 1"
