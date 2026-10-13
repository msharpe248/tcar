import unittest

from tcar.rotation import Rotation


class RotationTests(unittest.TestCase):
    def test_idle_then_dwell(self):
        rotation = Rotation(30, 20, True, 0)
        self.assertFalse(rotation.tick(29.99))
        self.assertTrue(rotation.tick(30))
        self.assertEqual(rotation.mode, "rotating")
        self.assertFalse(rotation.tick(49.99))
        self.assertTrue(rotation.tick(50))

    def test_input_pauses_and_restarts_idle_wait(self):
        rotation = Rotation(30, 20, True, 0)
        rotation.tick(30)
        rotation.activity(40)
        self.assertEqual(rotation.mode, "idle wait")
        self.assertFalse(rotation.tick(69.99))
        self.assertTrue(rotation.tick(70))

    def test_manually_paused_never_resumes_on_inactivity(self):
        rotation = Rotation(30, 20, True, 0)
        rotation.toggle(1)
        rotation.activity(2)
        self.assertEqual(rotation.mode, "paused")
        self.assertFalse(rotation.tick(100000))

    def test_resume_gives_current_machine_full_interval(self):
        rotation = Rotation(30, 20, False, 0)
        rotation.toggle(10)
        self.assertEqual(rotation.mode, "rotating")
        self.assertFalse(rotation.tick(29.99))
        self.assertTrue(rotation.tick(30))

    def test_manual_switch_gives_full_interval_with_short_idle_timeout(self):
        rotation = Rotation(5, 20, True, 0)
        rotation.activity(2, manual_switch=True)
        self.assertFalse(rotation.tick(21.99))
        self.assertTrue(rotation.tick(22))

    def test_delayed_tick_does_not_skip_multiple_machines(self):
        rotation = Rotation(30, 20, True, 0)
        self.assertTrue(rotation.tick(300))
        self.assertFalse(rotation.tick(300))
        self.assertFalse(rotation.tick(319))

    def test_zero_idle_timeout(self):
        rotation = Rotation(0, 20, True, 0)
        self.assertTrue(rotation.tick(0))
        self.assertFalse(rotation.tick(1))
