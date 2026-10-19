"""Final report statistics do not conflate income, balances or partial deaths."""

from tests.vnext.test_stratz_detail_projection import primary, project


def test_final_income_uses_full_duration_and_stratz_rates_not_last_minute():
    record = primary()
    record.data["players"][0]["goldPerMinute"] = 769
    record.data["players"][0]["experiencePerMinute"] = 900
    data = project(record)
    stats = data.players[0].final_stats
    assert stats.cumulative_gold_earned == 49497
    assert stats.gold_per_minute == 769 and stats.experience_per_minute == 900
    assert stats.earned_gold_net_worth_gap is None
    assert any(
        g.path == "players[0].final_stats.cumulative_gold_earned"
        and "floor(" in g.reason
        and len(g.source_paths) == 2
        for g in data.coverage.groups
    )


def test_missing_income_input_is_not_zero_but_explicit_zero_rate_is_zero():
    record = primary()
    record.data["players"][0]["goldPerMinute"] = 0
    record.data["players"][1].pop("goldPerMinute", None)
    data = project(record)
    assert data.players[0].final_stats.cumulative_gold_earned == 0
    assert data.players[1].final_stats.cumulative_gold_earned is None
    record.data["durationSeconds"] = None
    assert project(record).players[0].final_stats.cumulative_gold_earned is None


def test_complete_death_loss_uses_linked_amounts_and_partial_keeps_known_subtotal():
    record = primary()
    complete = project(record)
    stats = complete.players[0].final_stats
    expected = sum(e.gold_lost for e in complete.events.hero_deaths if e.victim_player_slot == 0)
    assert stats.death_gold_lost == stats.known_death_gold_lost == expected
    assert stats.death_gold_lost_count == stats.deaths
    record.data["players"][0]["playbackData"]["deathEvents"] = None
    partial = project(record).players[0].final_stats
    assert partial.death_gold_lost is None
    assert partial.known_death_gold_lost == 0 and partial.death_gold_lost_count == 0


def test_score_sums_buckets_without_using_the_terminal_bucket_or_player_kills():
    record = primary()
    record.data["radiantKills"] = [5, 20, 6, 0]
    record.data["direKills"] = [2, 30, 2, 0]
    data = project(record)
    assert data.match.score.radiant == 31 and data.match.score.dire == 34
    assert all(
        g.source_paths[0].source == "stratz"
        for g in data.coverage.groups
        if g.path.startswith("match.score.")
    )
