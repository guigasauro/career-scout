import unittest

from career_scout.normalize.positions import normalize, to_line


class TestNormalize(unittest.TestCase):
    def test_known(self):
        self.assertEqual(normalize("Centre-Back"), "CB")
        self.assertEqual(normalize("Goalkeeper"), "GK")

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize("Libero-Quarterback"))

    def test_generic_labels(self):
        self.assertEqual(normalize("Defender"), "DEF")
        self.assertEqual(normalize("Sweeper"), "DEF")
        self.assertEqual(normalize("Midfield"), "MID")
        self.assertEqual(normalize("Forward"), "ATT")

    def test_to_line(self):
        self.assertEqual(to_line("CB"), "DEF")
        self.assertEqual(to_line("ST"), "ATT")


if __name__ == "__main__":
    unittest.main()
