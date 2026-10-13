import unittest

from seed_clubs import norm_name, parse_tm_clubs, pick_club

# formato da busca do TM: caixa de jogadores (com link pro clube atual) antes da caixa de clubes
HTML = """
<div class="box"><h2 class="content-box-headline">Search results for players</h2>
  <table class="items"><tbody><tr><td><a href="/burgos-cf/startseite/verein/1536">Burgos</a>
  <img class="flaggenrahmen" title="Spain"></td></tr></tbody></table></div>
<div class="box"><h2 class="content-box-headline">Search results: Clubs - 3 Hits</h2>
  <table class="items"><tbody>
    <tr><td><a href="/carpi-fc-1909-u19/startseite/verein/27531">Carpi U19</a><img class="flaggenrahmen" title="Italy"></td></tr>
    <tr><td><a href="/carpi-b/startseite/verein/9">Carpi B</a><img class="flaggenrahmen" title="Italy"></td></tr>
    <tr><td><a href="/carpi-fc-1909/startseite/verein/4102">Carpi</a><img class="flaggenrahmen" title="Italy"></td></tr>
  </tbody></table></div>
"""


class TestSeedPick(unittest.TestCase):
    def test_only_clubs_box_and_skips_youth(self):
        rows = parse_tm_clubs(HTML)
        self.assertNotIn(("burgos-cf", 1536, "Spain"), rows)  # link da caixa de jogadores não conta
        self.assertEqual(pick_club(rows, {"Italy"}), ("carpi-fc-1909", 4102))

    def test_wrong_country_rejected(self):
        self.assertEqual(pick_club(parse_tm_clubs(HTML), {"Portugal"}), (None, None))

    def test_b_team_kept_when_name_says_so(self):
        rows = [("fc-barcelona-b", 2464, "Spain"), ("willem-ii-tilburg", 403, "Netherlands")]
        self.assertEqual(pick_club(rows, {"Spain"}, "FC Barcelona B"), ("fc-barcelona-b", 2464))
        self.assertEqual(pick_club(rows, {"Spain"}, "FC Barcelona"), (None, None))
        self.assertEqual(pick_club(rows, {"Netherlands"}, "Willem II"), ("willem-ii-tilburg", 403))

    def test_name_variants_match(self):
        self.assertEqual(norm_name("Arsenal FC"), norm_name("Arsenal"))
        self.assertEqual(norm_name("Sporting CP"), norm_name("Sporting"))
        self.assertNotEqual(norm_name("Real Sociedad"), norm_name("Real Sociedad B"))


if __name__ == "__main__":
    unittest.main()
