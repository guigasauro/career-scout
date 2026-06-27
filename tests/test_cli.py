import csv, tempfile, unittest
from pathlib import Path
from career_scout.cli import save_transfers, seasons_for
from career_scout.models import Transfer


def _t(**kw):
    base = dict(club_name="PSG", season=2017, window="Summer+Winter",
        player_name="X", player_url="", position_raw="Centre-Back",
        position_norm="CB", age=24, nationality="France", from_club="A",
        from_league="Ligue 1", transfer_type="permanent", fee=10_000_000.0)
    base.update(kw); return Transfer(**base)


class TestSaveTransfers(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.csv"
            save_transfers([_t(player_name="Mbappé")], p)
            rows = list(csv.DictReader(p.open(encoding="utf-8")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_name"], "Mbappé")
        self.assertIn("transfer_type", rows[0])

    def test_empty_noop(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.csv"
            save_transfers([], p)
            self.assertFalse(p.exists())


class TestSeasonsFor(unittest.TestCase):
    def test_matches_api_formula(self):
        self.assertEqual(seasons_for(22, 5), [2017, 2018, 2019, 2020, 2021])

    def test_length_equals_history(self):
        self.assertEqual(len(seasons_for(17, 7)), 7)
        self.assertEqual(seasons_for(17, 7)[-1], 2016)  # ceil = 2000+17-1
