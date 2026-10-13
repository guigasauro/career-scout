import unittest

from career_scout.analytics.budget import club_budget, percentile


class TestBudget(unittest.TestCase):
    def test_percentile_is_a_paid_value(self):
        fees = [1e6, 2e6, 3e6, 4e6, 5e6, 6e6, 7e6, 8e6, 9e6, 40e6]
        self.assertEqual(percentile(fees, 0.9), 9e6)      # o recorde de €40M não vira o orçamento

    def test_few_fees_uses_max(self):
        self.assertEqual(club_budget([2e6, 5e6]), 5e6)
        self.assertIsNone(club_budget([]))                 # sem compra paga: sem teto


if __name__ == "__main__":
    unittest.main()
