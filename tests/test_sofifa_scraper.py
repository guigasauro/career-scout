import unittest

from career_scout.match.sofifa_scraper import _looks_like_challenge, _parse_page, edition_number, league_label


class TestEditionNumber(unittest.TestCase):
    def test_fifa_label(self):
        self.assertEqual(edition_number("FIFA 23"), 23)

    def test_fc_label(self):
        self.assertEqual(edition_number("FC 24"), 24)
        self.assertEqual(edition_number("FC 26"), 26)

    def test_no_digits(self):
        self.assertIsNone(edition_number("edição sem número"))


class TestLooksLikeChallenge(unittest.TestCase):
    def test_detects_cloudflare_page(self):
        html = '<div id="cf-chl-widget-abc">Performing security verification</div>'
        self.assertTrue(_looks_like_challenge(html))

    def test_normal_page_passes(self):
        html = "<table><tbody><tr><td>Player</td></tr></tbody></table>"
        self.assertFalse(_looks_like_challenge(html))


class TestParsePageEditionFilter(unittest.TestCase):
    """SoFIFA reembaralha o pool em offsets altos e intercala linhas de OUTRA
    edição (href de jogador termina em /{versão}/ diferente do r_key pedido).
    Essas linhas têm que ser descartadas inteiras, não só ter o nome limpo."""

    ROW = """
    <td class="a1"><img id="{sofifa_id}"></td>
    <td><a href="/player/{sofifa_id}/some-player/{href_version}/">{name}</a>
        <span class="pos pos25">ST</span></td>
    <td>25</td><td>80</td><td>85</td>
    <td><a href="/team/1/some-club/">Some Club</a></td>
    <td>€10M</td>
    """

    def _html(self, rows: str) -> str:
        return f"<table><tbody>{rows}</tbody></table>"

    def test_matching_version_kept(self):
        html = self._html(f"<tr>{self.ROW.format(sofifa_id=1, href_version='260043', name='P. Pogba')}</tr>")
        rows, raw_count = _parse_page(html, "260043")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["short_name"], "P. Pogba")
        self.assertEqual(raw_count, 1)

    def test_mismatched_version_dropped_but_counted_raw(self):
        html = self._html(f"<tr>{self.ROW.format(sofifa_id=2, href_version='230054', name='E. Hazard')}</tr>")
        rows, raw_count = _parse_page(html, "260043")
        self.assertEqual(rows, [])
        self.assertEqual(raw_count, 1)  # página real, não pode parecer "fim da lista"



class TestLeagueLabel(unittest.TestCase):
    def test_top5_alias_only_in_right_country(self):
        self.assertEqual(league_label("Bundesliga", "Germany"), "German 1. Bundesliga")
        self.assertEqual(league_label("Bundesliga", "Austria"), "Bundesliga (Austria)")
        self.assertEqual(league_label("Premier League", "Ukraine"), "Premier League (Ukraine)")
        self.assertEqual(league_label("Serie A", "Ecuador"), "Serie A (Ecuador)")


if __name__ == "__main__":
    unittest.main()
