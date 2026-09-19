"""evals/run_retrieval.py's ship rule: keep the incumbent unless a candidate
wins on BOTH halves (board 2026-09-19 #7: best-on-dev recommended an overfit
pick, and a 0.001 tie was shipped by hand)."""
import unittest

import conftest_paths

ev = conftest_paths.load("evals/run_retrieval.py", "eval_rule")


class TestPick(unittest.TestCase):
    def test_a_tie_keeps_the_incumbent(self):
        s = {(1, 1, 1): (0.584, 0.587), (5, 2, 1): (0.618, 0.588)}
        self.assertEqual(ev.pick(s, (1, 1, 1), 0.025), (1, 1, 1))

    def test_winning_only_on_dev_keeps_the_incumbent(self):
        s = {(1, 1, 1): (0.584, 0.587), (10, 5, 1): (0.632, 0.569)}
        self.assertEqual(ev.pick(s, (1, 1, 1), 0.025), (1, 1, 1))

    def test_winning_on_both_halves_ships(self):
        s = {(1, 1, 1): (0.50, 0.50), (3, 1, 1): (0.60, 0.60), (5, 1, 1): (0.58, 0.56)}
        self.assertEqual(ev.pick(s, (1, 1, 1), 0.025), (3, 1, 1))


if __name__ == "__main__":
    unittest.main()
