import json
import tempfile
import unittest
from pathlib import Path

from gizmo_friend.brain.show_budget import MotionBudget, ShowBudget


class ShowBudgetTests(unittest.TestCase):
    budget_class = ShowBudget

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_device_and_global_caps_survive_restart(self):
        budget = self.budget_class(self.root, device_limit=2, global_limit=3)
        self.assertTrue(budget.reserve("a"))
        self.assertTrue(budget.reserve("a"))
        restarted = self.budget_class(self.root, device_limit=2, global_limit=3)
        self.assertFalse(restarted.reserve("a"))
        self.assertTrue(restarted.reserve("b"))
        self.assertFalse(restarted.reserve("c"))
        mirror = self.root / "devices/a" / f"{budget.ledger_name}.json"
        self.assertEqual(json.loads(mirror.read_text())[budget.counter], 2)


class MotionBudgetTests(ShowBudgetTests):
    budget_class = MotionBudget


if __name__ == "__main__":
    unittest.main()
