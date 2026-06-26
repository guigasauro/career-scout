import unittest

from career_scout.extract.transfermarkt import (
    _parse_value, _classify_transfer, parse_arrivals, _dedup_arrivals,
)
from career_scout.models import Transfer


ARRIVALS_HTML = """
<div class="box"><h2>Arrivals</h2>
<table class="items"><tbody>
  <tr class="odd">
    <td class="zentriert">1</td>
    <td><table class="inline-table">
      <tr><td><a href="/kylian-mbappe/profil/spieler/342229">Mbappé</a></td></tr>
      <tr><td>Centre-Forward</td></tr></table></td>
    <td class="zentriert">19</td>
    <td class="zentriert"><img title="France" src="x.png"/></td>
    <td><table class="inline-table">
      <tr><td class="hauptlink"><a href="/as-monaco">AS Monaco</a></td></tr>
      <tr><td><a href="/ligue1">Ligue 1</a></td></tr></table></td>
    <td class="rechts">€180.00m</td>
  </tr>
</tbody></table></div>
"""


class TestParseValue(unittest.TestCase):
    def test_millions(self):
        self.assertEqual(_parse_value("€10.00m"), 10_000_000.0)

    def test_thousands(self):
        self.assertEqual(_parse_value("€500k"), 500_000.0)

    def test_dash_is_none(self):
        self.assertIsNone(_parse_value("-"))


class TestClassify(unittest.TestCase):
    def test_end_of_loan(self):
        self.assertEqual(_classify_transfer("End of loan30/06/2022"), ("loan_return", 0.0))

    def test_loan_fee(self):
        self.assertEqual(_classify_transfer("Loan fee:€2.00m"), ("loan", 2_000_000.0))

    def test_plain_loan(self):
        self.assertEqual(_classify_transfer("Loan"), ("loan", 0.0))

    def test_free_transfer(self):
        self.assertEqual(_classify_transfer("free transfer"), ("free", 0.0))

    def test_permanent_fee(self):
        self.assertEqual(_classify_transfer("€10.00m"), ("permanent", 10_000_000.0))

    def test_permanent_unknown(self):
        self.assertEqual(_classify_transfer("-"), ("permanent", None))


class TestParseArrivals(unittest.TestCase):
    def test_single_arrival(self):
        out = parse_arrivals(ARRIVALS_HTML, "PSG", 2017, "Summer+Winter")
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(t.player_name, "Mbappé")
        self.assertEqual(t.position_norm, "ST")
        self.assertEqual(t.age, 19)
        self.assertEqual(t.nationality, "France")
        self.assertEqual(t.from_club, "AS Monaco")
        self.assertEqual(t.from_league, "Ligue 1")
        self.assertEqual(t.transfer_type, "permanent")
        self.assertEqual(t.fee, 180_000_000.0)

    def test_no_arrivals_box(self):
        self.assertEqual(parse_arrivals("<html></html>", "X", 2017, "w"), [])


def _t(player_name, transfer_type="permanent", season=2017, fee=None,
       from_club="Some FC", position_norm="CB"):
    return Transfer(
        club_name="PSG", season=season, window="Summer+Winter",
        player_name=player_name, player_url="",
        position_raw="Centre-Back", position_norm=position_norm,
        age=24, nationality="France", from_club=from_club, from_league="Ligue 1",
        transfer_type=transfer_type, fee=fee,
    )


class TestDedupArrivals(unittest.TestCase):
    def test_keeps_permanent_over_loan(self):
        rows = [
            _t("Player A", transfer_type="loan", season=2015),
            _t("Player A", transfer_type="permanent", season=2017),
        ]
        out = _dedup_arrivals(rows, "PSG")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].transfer_type, "permanent")
        self.assertEqual(out[0].season, 2017)

    def test_drops_internal_promotion(self):
        rows = [_t("Youngster", from_club="PSG U19")]
        out = _dedup_arrivals(rows, "PSG")
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
