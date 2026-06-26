import unittest

from career_scout.profile.aggregate import build_profiles, _mode
from career_scout.models import Transfer


def _t(player_name, position_norm, age=24, nationality="France",
       transfer_type="permanent", fee=10_000_000.0, season=2017):
    return Transfer(
        club_name="PSG", season=season, window="Summer+Winter",
        player_name=player_name, player_url="",
        position_raw="", position_norm=position_norm,
        age=age, nationality=nationality, from_club="Some FC",
        from_league="Ligue 1", transfer_type=transfer_type, fee=fee,
    )


class TestMode(unittest.TestCase):
    def test_mode_with_support(self):
        self.assertEqual(_mode(["a", "a", "b"], min_support=2), "a")

    def test_mode_without_support(self):
        self.assertIsNone(_mode(["a", "b"], min_support=2))


class TestBuildProfiles(unittest.TestCase):
    def test_cb_profile(self):
        transfers = [
            _t("A", "CB", age=22, nationality="France"),
            _t("B", "CB", age=24, nationality="France"),
            _t("C", "CB", age=26, nationality="Brazil"),
        ]
        profiles = build_profiles(transfers, min_sample=3, min_support=2)
        cb = next(p for p in profiles if p.position_norm == "CB")
        self.assertEqual(cb.n, 3)
        self.assertEqual(cb.nationality_mode, "France")
        self.assertEqual(cb.age_mean, 24.0)

    def test_single_below_sample_folds_into_line(self):
        transfers = [_t("Solo", "LW")]
        profiles = build_profiles(transfers, min_sample=3, min_support=2)
        positions = {p.position_norm for p in profiles}
        # LW (n=1) does not stand alone; folds into ATT line, which also has n=1
        self.assertNotIn("LW", positions)


if __name__ == "__main__":
    unittest.main()
