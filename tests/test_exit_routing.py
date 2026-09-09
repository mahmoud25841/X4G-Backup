import asyncio
import sys
import types


def load_bridge():
    fake_main = types.SimpleNamespace(LINKS={})
    sys.modules["main"] = fake_main
    import exit_routing
    return exit_routing, fake_main


def test_region_from_label():
    bridge, main = load_bridge()
    uid = "u1"
    main.LINKS[uid] = {"label": "NL - Premium"}
    assert bridge._region_for_uuid(uid) == "NL"


def test_region_from_explicit_field():
    bridge, main = load_bridge()
    uid = "u2"
    main.LINKS[uid] = {"label": "Premium", "region": "GB"}
    assert bridge._region_for_uuid(uid) == "GB"


def test_unknown_label_has_no_region():
    bridge, main = load_bridge()
    uid = "u3"
    main.LINKS[uid] = {"label": "Premium"}
    assert bridge._region_for_uuid(uid) is None
