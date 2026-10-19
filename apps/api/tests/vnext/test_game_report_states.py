"""Observed states have explicit boundaries; purchases cannot activate buffs."""

from tests.vnext.test_stratz_detail_projection import primary, project, supplement


def test_levels_use_the_latest_observation_and_preserve_unknown_assists():
    record = primary(9040460429)
    record.data["players"][0]["playbackData"]["playerUpdateLevelEvents"] = [
        {"time": -30, "level": 1},
        {"time": 61, "level": 2},
        {"time": 121, "level": 3},
    ]
    data = project(record, supplement(record))
    nodes = data.players[0].minute_timeline
    assert [n.level for n in nodes[:3]] == [1, 1, 2]
    assert [(e.time_seconds, e.level) for e in data.players[0].level_events] == [
        (-30, 1), (61, 2), (121, 3)
    ]
    assert all(not any("observed_at" in key for key in n.model_dump()) for n in nodes)
    assert all(n.assists is None for n in nodes)
    assert nodes[2].level != data.players[0].final_stats.level


def test_known_skill_ranks_are_one_based_but_unknown_skill_is_not_guessed():
    record = primary()
    raw = record.data["players"][0]["playbackData"]["abilityLearnEvents"]
    raw[0].update(level=0, isTalent=False, isUltimate=False)
    raw[1].update(abilityId=0, level=0, isTalent=True)
    build = project(record).builds.players[0]
    assert build.ability_upgrade_events[0].level == 1
    assert build.ability_upgrade_events[1].ability is None
    assert build.ability_upgrade_events[1].level is None
    assert build.ability_upgrade_events[1].is_talent is True


def test_consumed_scepter_is_an_explicit_buff_not_a_purchase_or_held_item():
    record = primary()
    player = record.data["players"][0]
    player["stats"]["matchPlayerBuffEvent"] = [
        {"time": 1000, "itemId": 108, "abilityId": None, "stackCount": 1}
    ]
    build = project(record).builds.players[0]
    assert build.final_loadout.has_consumed_scepter is True
    assert build.permanent_upgrade_events[0].time_seconds == 1000
    assert build.final_loadout.has_shard is None
    player["stats"]["matchPlayerBuffEvent"] = []
    player["stats"]["itemPurchases"].append({"time": 1000, "itemId": 108})
    assert project(record).builds.players[0].final_loadout.has_consumed_scepter is None
