import unittest

from career_scout.analytics.statsbomb import aggregate_match


def _lineup(team, pid, name, frm="00:00", to=None):
    return {"team_name": team, "lineup": [{
        "player_id": pid, "player_name": name, "player_nickname": None, "country": {"name": "X"},
        "positions": [{"position": "Center Forward", "from": frm, "to": to}],
    }]}


def _ev(eid, kind, pid, minute=10, location=(60, 40), **extra):
    return {"id": eid, "type": {"name": kind}, "player": {"id": pid}, "minute": minute,
            "second": 0, "location": list(location), **extra}


class TestAggregateMatch(unittest.TestCase):
    def setUp(self):
        self.lineups = [_lineup("A", 1, "Passer"), _lineup("B", 2, "Sub", frm="60:00")]
        self.events = [
            # passe completo de 20 jardas pra dentro da área, que vira chute de 0.3 xG
            _ev("p1", "Pass", 1, location=(90, 40), **{"pass": {"end_location": [110, 40], "assisted_shot_id": "s1", "shot_assist": True}}),
            _ev("s1", "Shot", 1, **{"shot": {"statsbomb_xg": 0.3, "type": {"name": "Open Play"}, "outcome": {"name": "Goal"}}}),
            _ev("s2", "Shot", 2, **{"shot": {"statsbomb_xg": 0.76, "type": {"name": "Penalty"}, "outcome": {"name": "Saved"}}}),
            _ev("p2", "Pass", 2, **{"pass": {"end_location": [70, 40], "outcome": {"name": "Incomplete"}}}),
            _ev("r1", "Ball Receipt*", 1, location=(110, 40)),                                   # recepção na área
            _ev("r2", "Ball Receipt*", 1, location=(110, 40), ball_receipt={"outcome": {"name": "Incomplete"}}),
            _ev("c1", "Carry", 1, location=(95, 40), carry={"end_location": [105, 40]}),          # conduz pra área
            _ev("c2", "Carry", 1, location=(105, 40), carry={"end_location": [110, 40]}),         # já estava dentro
            _ev("end", "Half End", None, minute=90),
        ]

    def test_player_stats(self):
        players, _ = aggregate_match(self.events, self.lineups)
        a, b = players[1], players[2]
        self.assertEqual(a["minutes"], 90)
        self.assertEqual(b["minutes"], 30)                     # entrou aos 60
        self.assertAlmostEqual(a["xa"], 0.3)
        self.assertEqual((a["progressive_passes"], a["passes_into_box"]), (1, 1))
        self.assertEqual((b["passes"], b["passes_completed"]), (1, 0))
        self.assertAlmostEqual(b["npxg"], 0.0)                 # pênalti fora do npxG
        self.assertAlmostEqual(b["xg"], 0.76)
        self.assertEqual((a["npg"], b["npg"]), (1, 0))                  # gol de jogada conta; pênalti não marcou
        self.assertEqual((a["box_receptions"], a["carries_into_box"]), (1, 1))

    def test_team_against(self):
        _, teams = aggregate_match(self.events, self.lineups)
        self.assertAlmostEqual(teams["A"]["xg_against"], 0.76)
        self.assertEqual(teams["B"]["goals_against"], 1)
        self.assertAlmostEqual(teams["A"]["passes_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
