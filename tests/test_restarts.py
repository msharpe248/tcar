import unittest

from tcar.restarts import Restarts


class RestartTests(unittest.TestCase):
    def test_third_attempt_in_minute_fails(self):
        policy = Restarts(3, 60, 0)
        self.assertEqual(policy.observe("one", "1", True, 0), "restart")
        self.assertIsNone(policy.observe("one", "1", True, 0.5))
        self.assertEqual(policy.observe("one", "2", True, 1), "restart")
        self.assertEqual(policy.observe("one", "3", True, 2), "failed")
        self.assertIsNone(policy.observe("one", "3", True, 1000))
        self.assertTrue(policy.has_failures)

    def test_rolling_window_expires_and_sessions_are_independent(self):
        policy = Restarts(3, 60, 0)
        self.assertEqual(policy.observe("one", "1", True, 0), "restart")
        self.assertEqual(policy.observe("one", "2", True, 30), "restart")
        self.assertEqual(policy.observe("one", "3", True, 60), "restart")
        self.assertEqual(policy.observe("two", "4", True, 60), "restart")

    def test_delay_and_manual_retry(self):
        policy = Restarts(1, 60, 1)
        self.assertIsNone(policy.observe("one", "1", True, 0))
        self.assertEqual(policy.observe("one", "1", True, 1), "failed")
        self.assertEqual(policy.observe("one", "2", False, 2, "2"), "reset")
        self.assertFalse(policy.has_failures)
        self.assertIsNone(policy.observe("one", "2", True, 3, "2"))
        self.assertEqual(policy.observe("one", "2", True, 4, "2"), "failed")

    def test_manual_restart_of_running_command_resets_only_its_budget(self):
        policy = Restarts(3, 60, 0)
        for window in ("one", "two"):
            self.assertEqual(policy.observe(window, "1", True, 0), "restart")
            self.assertEqual(policy.observe(window, "2", True, 1), "restart")
        self.assertIsNone(policy.observe("one", "3", False, 2))
        self.assertEqual(policy.observe("one", "4", False, 3, "4"), "reset")
        self.assertEqual(policy.observe("two", "3", True, 3), "failed")
        self.assertEqual(policy.observe("one", "4", True, 4, "4"), "restart")
        self.assertEqual(policy.observe("one", "5", True, 5, "4"), "restart")
        self.assertEqual(policy.observe("one", "6", True, 6, "4"), "failed")

    def test_manual_restart_clears_pending_delay_and_retry(self):
        policy = Restarts(3, 60, 1)
        self.assertIsNone(policy.observe("one", "1", True, 0))
        self.assertEqual(policy.observe("one", "2", True, 0.5, "2"), "reset")
        self.assertIsNone(policy.observe("one", "2", True, 0.75, "2"))
        self.assertEqual(policy.observe("one", "2", True, 1.75, "2"), "restart")
        self.assertEqual(policy.observe("one", "3", False, 2, "3"), "reset")
        self.assertIsNone(policy.observe("one", "3", True, 3, "3"))
        self.assertEqual(policy.observe("one", "3", True, 4, "3"), "restart")
