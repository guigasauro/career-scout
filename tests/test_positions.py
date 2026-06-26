import unittest

from career_scout.normalize.positions import normalize, to_line


class TestNormalize(unittest.TestCase):
    def test_known(self):
        self.assertEqual(normalize("Centre-Back"), "CB")
        self.assertEqual(normalize("Goalkeeper"), "GK")

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize("Sweeper"))

    def test_to_line(self):
        self.assertEqual(to_line("CB"), "DEF")
        self.assertEqual(to_line("ST"), "ATT")


if __name__ == "__main__":
    unittest.main()
