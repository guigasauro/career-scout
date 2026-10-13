import unittest

from career_scout.analytics.deficiencies import deficiencies


def _team(name, rank, npxg_against, npxg=40):
    base = dict(team=name, rank=rank, matches=38, npxg=npxg, shots=400, xa=30, passes_into_box=300,
                progressive_passes=1500, passes=15000, passes_completed=12000, dribbles_completed=300,
                passes_share=0.5, npxg_against=npxg_against, shots_against=400, passes_into_box_against=300,
                progressive_passes_against=1500, pressures=5000, tackles_won=500, interceptions=400, aerials_won=600)
    return {k: str(v) for k, v in base.items()}


class TestDeficiencies(unittest.TestCase):
    def setUp(self):
        # D sofre muito mais xG que o top 2 e ataca igual
        self.teams = [_team("A", 1, 30), _team("B", 2, 32), _team("C", 3, 40), _team("D", 4, 60)]

    def test_worst_first_and_against_inverted(self):
        rows = deficiencies(self.teams, "D", target=(1, 2))
        self.assertEqual(rows[0]["metric"], "npxg_against")   # "contra" alto = deficiência
        self.assertLess(rows[0]["gap"], 0)
        self.assertEqual(rows[0]["pct"], 0)                    # pior da liga nisso

    def test_strength_has_positive_gap(self):
        teams = self.teams + [_team("E", 5, 40, npxg=60)]
        rows = deficiencies(teams, "E", target=(1, 2))
        by = {r["metric"]: r for r in rows}
        self.assertGreater(by["npxg"]["gap"], 0)               # ataca mais que o alvo
        self.assertEqual(by["npxg"]["pct"], 100)
        self.assertIn(rows[-1]["metric"], ("npxg", "xg_per_shot"))  # força no fim da lista


if __name__ == "__main__":
    unittest.main()
