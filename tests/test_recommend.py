import unittest

from career_scout.analytics.recommend import rank_role, role_of, roles_of


def _p(name, team, minutes, positions, **stats):
    base = dict(player_id=name, player=name, team=team, minutes=str(minutes), position=positions.split(":")[0], positions=positions,
                passes="100", passes_completed="80", shots="0", npxg="0")
    base.update({k: str(v) for k, v in stats.items()})
    return base


class TestRoles(unittest.TestCase):
    def test_role_of(self):
        self.assertEqual(role_of("Left Center Back"), "CB")
        self.assertEqual(role_of("Right Wing Back"), "FB")
        self.assertEqual(role_of("Left Defensive Midfield"), "DM")
        self.assertEqual(role_of("Right Midfield"), "W")
        self.assertEqual(role_of("Center Forward"), "ST")
        self.assertEqual(role_of("Right Center Midfield"), "CM")

    def test_roles_of_splits_minutes(self):
        r = roles_of({"position": "Center Attacking Midfield", "positions": "Center Attacking Midfield:600;Right Wing:300;Left Wing:100"})
        self.assertAlmostEqual(r["AM"], 0.6)
        self.assertAlmostEqual(r["W"], 0.4)


class TestRankRole(unittest.TestCase):
    def setUp(self):
        self.share = {"A": 0.5, "B": 0.5, "C": 0.5}
        self.players = [
            _p("Mine", "A", 1800, "Right Wing:1800", xa=2),
            _p("Best", "B", 1800, "Left Wing:1800", xa=8),
            _p("Mid", "C", 1800, "Right Wing:900;Center Forward:900", xa=4),   # 50% na ponta: entra
            _p("Rare", "C", 1800, "Center Forward:1500;Right Wing:300", xa=20), # 17% na ponta: fora
            _p("Few", "B", 400, "Left Wing:400", xa=30),                         # poucos minutos: fora
        ]

    def test_ranking_pool_and_current(self):
        cands, current = rank_role(self.players, self.share, "W", {"xa": 1}, exclude_team="A")
        self.assertEqual([c["player"] for c in cands], ["Best", "Mid"])
        self.assertEqual([c["player"] for c in current], ["Mine"])
        self.assertEqual(cands[0]["score"], 1.0)
        self.assertEqual(current[0]["score"], 0.0)   # pior do pool que inclui o próprio time


if __name__ == "__main__":
    unittest.main()


class TestCrossLeague(unittest.TestCase):
    def test_percentile_within_league_times_strength(self):
        from career_scout.analytics.recommend import league_factor
        share = {"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5}
        players = [
            {**_p("EsBest", "A", 1800, "Left Wing:1800", xa=5), "league": "la-liga"},
            {**_p("EsLow", "B", 1800, "Left Wing:1800", xa=1), "league": "la-liga"},
            # números absolutos maiores na Ligue 1, mas o percentil é contra os pares da liga dele
            {**_p("FrBest", "C", 1800, "Left Wing:1800", xa=9), "league": "ligue-1"},
            {**_p("FrLow", "D", 1800, "Left Wing:1800", xa=8), "league": "ligue-1"},
        ]
        cands, _ = rank_role(players, share, "W", {"xa": 1})
        by = {c["player"]: c["score"] for c in cands}
        self.assertEqual(by["EsBest"], round(1.0 * league_factor("la-liga"), 3))
        self.assertEqual(by["FrBest"], round(1.0 * league_factor("ligue-1"), 3))
        self.assertGreater(by["EsBest"], by["FrBest"])   # mesmo topo da liga, liga mais forte vale mais
        self.assertEqual(by["FrLow"], 0.0)                # xA 8 é o pior da Ligue 1
