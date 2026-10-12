import csv
import tempfile
import unittest
from pathlib import Path

from career_scout.match.sofifa import (
    _load_sofifa_cached,
    league_names,
    line_of_pos,
    load_sofifa,
    rank_candidates,
    team_line_overall,
)
from career_scout.models import PositionProfile


def _p(sofifa_id, nationality, age, value_eur, positions,
       club_name="Other FC", league_name="French Ligue 1", overall=80,
       club_position="", potential=0):
    return {
        "sofifa_id": sofifa_id,
        "short_name": f"Player {sofifa_id}",
        "club_name": club_name,
        "league_name": league_name,
        "nationality_name": nationality,
        "age": str(age),
        "value_eur": str(value_eur),
        "overall": str(overall),
        "potential": str(potential),
        "club_position": club_position,
        "player_positions": positions,
    }


class TestRankCandidates(unittest.TestCase):
    def setUp(self):
        self.profile = PositionProfile(
            position_norm="CB", n=3, n_permanent=3, age_mean=24.0,
            fee_mean=10_000_000.0, nationality_mode="France",
            from_league_mode="Ligue 1", from_club_mode=None,
        )
        self.players = [
            _p("1", "France", 24, 10_000_000, "CB"),                       # French CB near target
            _p("2", "Brazil", 24, 10_000_000, "CB"),                       # identical non-French CB
            _p("3", "England", 25, 12_000_000, "ST"),                      # position mismatch
            _p("4", "France", 24, 10_000_000, "CB", club_name="ExcludeMe"),  # excluded club
        ]

    def test_position_mismatch_filtered(self):
        results = rank_candidates(self.profile, self.players, top_n=20,
                                  exclude_club="ExcludeMe")
        ids = {c.sofifa_id for c in results}
        self.assertNotIn("3", ids)

    def test_excluded_club_absent(self):
        results = rank_candidates(self.profile, self.players, top_n=20,
                                  exclude_club="ExcludeMe")
        ids = {c.sofifa_id for c in results}
        self.assertNotIn("4", ids)

    def test_sorted_descending(self):
        results = rank_candidates(self.profile, self.players, top_n=20,
                                  exclude_club="ExcludeMe")
        scores = [c.score for c in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_french_outranks_identical_non_french(self):
        results = rank_candidates(self.profile, self.players, top_n=20,
                                  exclude_club="ExcludeMe")
        by_id = {c.sofifa_id: c for c in results}
        self.assertGreater(by_id["1"].score, by_id["2"].score)

    def test_fee_discount_shifts_target(self):
        # fee_mean=10M, α=0.8 → alvo real = 8M. Jogador a 8M deve casar melhor que a 10M.
        players = [
            _p("at8",  "France", 24, 8_000_000,  "CB"),
            _p("at10", "France", 24, 10_000_000, "CB"),
        ]
        by_id = {c.sofifa_id: c.score for c in
                 rank_candidates(self.profile, players, fee_discount=0.8)}
        self.assertGreater(by_id["at8"], by_id["at10"])
        # α=1.0 inverte: alvo volta a 10M
        by_id = {c.sofifa_id: c.score for c in
                 rank_candidates(self.profile, players, fee_discount=1.0)}
        self.assertGreater(by_id["at10"], by_id["at8"])

    def test_value_log_keeps_expensive_player_in_play(self):
        # pool dominado por jogadores baratos: std linear pequeno zera o eixo de valor
        # pra quem custa 5× o alvo (8M); em log ele ainda pontua
        players = [_p(str(i), "Brazil", 24, 500_000, "CB") for i in range(20)]
        players.append(_p("star", "Brazil", 24, 40_000_000, "CB"))
        def value_pts(**kw):
            c = next(c for c in rank_candidates(self.profile, players, top_n=50, **kw) if c.sofifa_id == "star")
            return c.breakdown["value"][0]
        self.assertEqual(value_pts(), 0)
        self.assertGreater(value_pts(value_log=True), 0)

    def test_upgrade_scales_value_target(self):
        # mercado: overall 80 vale 8M, overall 83 vale 16M; alvo do histórico = 8M.
        # Upgrade (+3 sobre elenco 80) dobra o valor-alvo → quem vale 16M casa no valor.
        players = [_p(f"a{i}", "Brazil", 24, 8_000_000, "CB", overall=80) for i in range(3)]
        players += [_p(f"b{i}", "Brazil", 24, 16_000_000, "CB", overall=83) for i in range(3)]
        def value_pts(pid, **kw):
            return next(c for c in rank_candidates(self.profile, players, top_n=10, **kw)
                        if c.sofifa_id == pid).breakdown["value"][0]
        self.assertGreater(value_pts("a0", team_overall=80.0), value_pts("b0", team_overall=80.0))
        self.assertGreater(value_pts("b0", team_overall=80.0, level_offset=3),
                           value_pts("a0", team_overall=80.0, level_offset=3))

    def test_score_normalized_to_unit_range(self):
        # perfeito em todos os eixos ativos → score == 1.0 (não a soma dos pesos)
        # fee_discount=1.0 para o candidato a 10M cair exatamente no alvo
        results = rank_candidates(self.profile, self.players, top_n=20,
                                  exclude_club="ExcludeMe", fee_discount=1.0)
        self.assertAlmostEqual(max(c.score for c in results), 1.0, places=4)

    def test_breakdown_sums_to_score(self):
        results = rank_candidates(self.profile, self.players, top_n=20, exclude_club="ExcludeMe")
        for c in results:
            got = sum(g for g, _ in c.breakdown.values())
            self.assertLessEqual(abs(got - c.score * 100), len(c.breakdown))  # tolerância de arredondamento
            self.assertAlmostEqual(sum(m for _, m in c.breakdown.values()), 100, delta=len(c.breakdown))

    def test_potential_knob_reorders(self):
        players = [
            _p("low", "France", 24, 10_000_000, "CB"),   # encaixe perfeito, sem potencial
            _p("hi",  "France", 24, 10_000_000, "CB"),   # idem + potencial alto
        ]
        players[0]["potential"] = "75"
        players[1]["potential"] = "92"
        off = {c.sofifa_id: c.score for c in rank_candidates(self.profile, players)}
        self.assertAlmostEqual(off["low"], off["hi"], places=4)  # knob off → empate
        on = {c.sofifa_id: c.score for c in
              rank_candidates(self.profile, players, potential_weight=0.5)}
        self.assertGreater(on["hi"], on["low"])                  # knob on → joia sobe


class TestRealismLevel(unittest.TestCase):
    def setUp(self):
        # perfil sem fee/nac/liga: isola o eixo de nível (overall)
        self.profile = PositionProfile(
            position_norm="MID", n=3, n_permanent=3, age_mean=24.0,
            fee_mean=None, nationality_mode=None, from_league_mode=None,
            from_club_mode=None,
        )
        self.players = [
            _p("near", "X", 24, 5_000_000, "CM", overall=79),  # no nível do time
            _p("low",  "X", 24, 5_000_000, "CM", overall=68),  # bem abaixo
            _p("high", "X", 24, 5_000_000, "CM", overall=90),  # acima demais
        ]

    def test_anchors_on_team_level(self):
        res = {c.sofifa_id: c.score for c in
               rank_candidates(self.profile, self.players, team_overall=79.0)}
        self.assertGreater(res["near"], res["low"])
        self.assertGreater(res["near"], res["high"])

    def test_upgrade_offset_favors_stronger(self):
        # offset +6 → alvo 85, o jogador de 90 fica mais perto que o de 79
        res = {c.sofifa_id: c.score for c in
               rank_candidates(self.profile, self.players, team_overall=79.0, level_offset=6)}
        self.assertGreater(res["high"], res["near"])

    def test_threshold_filters_pool(self):
        full = rank_candidates(self.profile, self.players, team_overall=79.0)
        strict = rank_candidates(self.profile, self.players, team_overall=79.0,
                                 score_threshold=0.99)
        self.assertLess(len(strict), len(full))

    def test_sort_by_overall(self):
        res = rank_candidates(self.profile, self.players, team_overall=79.0,
                              sort_by="overall")
        self.assertEqual([c.overall for c in res], sorted([c.overall for c in res], reverse=True))


class TestTeamLineOverall(unittest.TestCase):
    def test_starters_only(self):
        players = [
            _p("1", "X", 24, 0, "CM", club_name="FC", overall=80, club_position="LCM"),
            _p("2", "X", 24, 0, "CM", club_name="FC", overall=78, club_position="RCM"),
            _p("3", "X", 24, 0, "CM", club_name="FC", overall=60, club_position="SUB"),  # banco
        ]
        lvl = team_line_overall(players, "FC")
        self.assertEqual(lvl["MID"], 79.0)  # ignora o reserva de 60

    def test_fallback_starters_per_line_when_no_starter(self):
        # sem titular marcado: N melhores por linha num 4-4-2 (GK 1, ATT 2)
        players = [
            _p(str(i), "X", 24, 0, "ST", club_name="FC", overall=ov, club_position="SUB")
            for i, ov in enumerate([70, 72, 74, 50])
        ] + [_p(f"g{i}", "X", 24, 0, "GK", club_name="FC", overall=ov, club_position="SUB")
             for i, ov in enumerate([87, 70, 65])]
        lvl = team_line_overall(players, "FC")
        self.assertEqual(lvl["ATT"], 73.0)  # top-2 (74, 72)
        self.assertEqual(lvl["GK"], 87.0)   # só o titular; reservas não puxam pra baixo

    def test_line_of_pos(self):
        self.assertEqual(line_of_pos("CM"), "MID")
        self.assertEqual(line_of_pos("DEF"), "DEF")   # já é linha


class TestSofifaCache(unittest.TestCase):
    def _tmp_csv(self, d):
        p = Path(d) / "players_99.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["short_name", "league_name", "player_positions"])
            w.writerow(["A", "French Ligue 1", "CB"])
            w.writerow(["B", "Italian Serie A", "ST"])
        return p

    def test_independent_lists(self):
        _load_sofifa_cached.cache_clear()
        with tempfile.TemporaryDirectory() as d:
            p = self._tmp_csv(d)
            a = load_sofifa(p)
            b = load_sofifa(p)
            self.assertIsNot(a, b)  # listas separadas, parse compartilhado
            self.assertEqual(len(a), 2)

    def test_league_names(self):
        _load_sofifa_cached.cache_clear()
        with tempfile.TemporaryDirectory() as d:
            p = self._tmp_csv(d)
            self.assertEqual(league_names(p), {"French Ligue 1", "Italian Serie A"})


if __name__ == "__main__":
    unittest.main()
