import unittest
from datetime import date

from career_scout.analytics.market import match_squad, name_score, parse_squad

HEAD = ["#", "Player", "Date of birth/Age", "Nat.", "Current club", "Height", "Foot", "Joined", "Signed from", "Market value"]


def _row(pid, name, born, value, height="1,80m", foot="right"):
    cells = ["7", f'<td class="hauptlink"><a href="/x/profil/spieler/{pid}">{name}</a></td>', f"{born} (24)", "", "", height, foot, "", "", value]
    return "<tr>" + "".join(c if c.startswith("<td") else f"<td>{c}</td>" for c in cells) + "</tr>"


class TestParseSquad(unittest.TestCase):
    def test_parses_birth_value_height(self):
        html = ('<table class="items"><thead><tr>' + "".join(f"<th>{h}</th>" for h in HEAD) + "</tr></thead><tbody>"
                + _row(108390, "Thibaut Courtois", "11/05/1992", "€35.00m", "1,99m", "left")
                + _row(128898, "Jamal Blackman", "27/10/1993", "€250k") + "</tbody></table>")
        a, b = parse_squad(html)
        self.assertEqual((a["tm_player_id"], a["birth"], a["value"], a["height"], a["foot"]),
                         (108390, date(1992, 5, 11), 35_000_000, "1.99", "left"))
        self.assertEqual(b["value"], 250_000)


class TestNames(unittest.TestCase):
    def test_variants_match(self):
        for a, b in [("Timothy Michael Krul", "Tim Krul"), ("Baba Rahman", "Abdul Rahman Baba"),
                     ("Son Heung-Min", "Heung-min Son"), ("Petr Čech", "Petr Cech"), ("Falcao", "Radamel Falcao")]:
            self.assertGreaterEqual(name_score(a, b), 0.6, (a, b))

    def test_first_name_only_does_not_match(self):
        self.assertLess(name_score("Leon Osman", "Leon Schaffran"), 0.6)

    def test_closest_full_name_wins_tie(self):
        squad = [{"tm_name": "Jerome Binnom-Williams"}, {"tm_name": "Jonny Williams"}]
        got = match_squad([{"player_id": "1", "player": "Jonathan Williams"}], squad)
        self.assertEqual(got["1"]["tm_name"], "Jonny Williams")


if __name__ == "__main__":
    unittest.main()
