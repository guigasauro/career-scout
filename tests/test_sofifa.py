import unittest

from career_scout.match.sofifa import rank_candidates
from career_scout.models import PositionProfile


def _p(sofifa_id, nationality, age, value_eur, positions,
       club_name="Other FC", league_name="French Ligue 1", overall=80):
    return {
        "sofifa_id": sofifa_id,
        "short_name": f"Player {sofifa_id}",
        "club_name": club_name,
        "league_name": league_name,
        "nationality_name": nationality,
        "age": str(age),
        "value_eur": str(value_eur),
        "overall": str(overall),
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


if __name__ == "__main__":
    unittest.main()
