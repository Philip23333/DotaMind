"""Support actions and damage directions retain their source meanings."""

from tests.vnext.test_stratz_detail_projection import primary, project, supplement


def test_dispenser_use_is_not_a_placed_observer_or_sentry():
    record = primary()
    player = record.data["players"][0]
    player["playbackData"]["itemUsedEvents"] = [{"time": 100, "itemId": 218}]
    player["stats"]["itemUsed"] = [{"itemId": 218, "count": 1}]
    data = project(record)
    events = data.players[0].support.events
    assert [(e.item.id, e.action, e.time_seconds) for e in events if e.action == "used"] == [
        (218, "used", 100)
    ]
    assert not any(e.action == "placed" for e in events)
    assert not any(e.action == "used" and e.item.id in (42, 43) for e in events)


def test_empty_stratz_ward_groups_use_same_game_opendota_without_expiry_as_kill():
    record = primary(9040460429)
    for player in record.data["players"]:
        player["stats"]["wards"] = []
        player["stats"]["wardDestruction"] = []
    extra = supplement(record)
    data = project(record, extra)
    for i, player in enumerate(data.players):
        raw = extra.data["players"][i]
        placed = [e for e in player.support.events if e.action == "placed"]
        assert len(placed) == len(raw.get("obs_log") or []) + len(raw.get("sen_log") or [])
        assert all(e.source_paths[0].source == "opendota" for e in placed)
        assert not any(e.action == "destroyed" for e in player.support.events)


def test_received_damage_retains_attacker_identity_without_forcing_root_total():
    record = primary()
    player = record.data["players"][0]
    other = record.data["players"][5]
    player["stats"]["heroDamageReport"]["receivedTargets"] = [
        {"target": other["heroId"], "amount": 1234}
    ]
    data = project(record)
    received = data.interactions.players[0].damage_received_by_source
    assert received[0].source_hero.id == other["heroId"] and received[0].value == 1234
    assert data.players[0].final_stats.hero_damage == player["heroDamage"]
