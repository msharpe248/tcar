import unittest

from tcar.config import Config
from tcar.keys import Event, InputRouter, PASTE_END, PASTE_START, prefix_sequence


def forwarded(events):
    return b"".join(event.value for event in events if event.kind != "action")


class InputTests(unittest.TestCase):
    def router(self, prefix="C-g", **bindings):
        config = Config((), prefix=prefix)
        config.bindings.update(bindings)
        return InputRouter(prefix_sequence(prefix), config.input_bindings())

    def test_ordinary_input_is_byte_exact(self):
        router = self.router()
        data = "héllo 👻".encode() + b"\x03\x04\t\r\x7f\x1b[A\x1bOD"
        self.assertEqual(forwarded(router.feed(data, 0)), data)

    def test_every_partition_of_arrow_chord(self):
        data = b"\x07\x1b[C"
        for mask in range(1 << (len(data) - 1)):
            router = self.router()
            events, start = [], 0
            for i in range(1, len(data)):
                if mask & (1 << (i - 1)):
                    events += router.feed(data[start:i], 0)
                    start = i
            events += router.feed(data[start:], 0)
            self.assertEqual(events, [Event("action", "next")])

    def test_application_cursor_arrow(self):
        self.assertEqual(self.router().feed(b"\x07\x1bOD", 0), [Event("action", "previous")])

    def test_multiple_keys_and_switches_in_one_read(self):
        events = self.router().feed(b"before\x07\x1b[Cafter\x07qignored", 0)
        self.assertEqual(events, [Event("data", b"before"), Event("action", "next"),
                                  Event("data", b"after"), Event("action", "quit"), Event("data", b"ignored")])

    def test_double_prefix_then_more_typing(self):
        events = self.router().feed(b"\x07\x07abc", 0)
        self.assertEqual(forwarded(events), b"\x07abc")
        self.assertEqual(events[0].kind, "literal_prefix")

    def test_unknown_chord_forwards_both_keys(self):
        self.assertEqual(forwarded(self.router().feed(b"\x07xabc", 0)), b"\x07xabc")

    def test_unknown_escape_chord_forwards_whole_sequence(self):
        data = b"\x07\x1b[9;3~tail"
        self.assertEqual(forwarded(self.router().feed(data, 0)), data)

    def test_prefix_does_not_expire(self):
        router = self.router()
        self.assertEqual(router.feed(b"\x07", 0), [])
        self.assertEqual(router.feed(b"", 100), [])
        self.assertTrue(router.prefixed)
        self.assertEqual(router.feed(b"q", 101), [Event("action", "quit")])

    def test_escape_key_timeout(self):
        router = self.router(quit="Escape")
        self.assertEqual(router.feed(b"\x07\x1b", 0), [])
        self.assertEqual(router.feed(b"", 0.05), [])
        self.assertEqual(router.feed(b"", 0.11), [Event("action", "quit")])

    def test_truncated_escape_preserved(self):
        router = self.router()
        self.assertEqual(router.feed(b"\x1b[", 0), [])
        self.assertEqual(forwarded(router.feed(b"", 0.11)), b"\x1b[")

    def test_paste_cannot_switch_or_quit_even_across_reads(self):
        data = PASTE_START + b"hello\x07q\x07\x1b[C\x07\x07" + PASTE_END + b"tail"
        router = self.router()
        events = []
        for byte in data:
            events += router.feed(bytes([byte]), 0)
        self.assertEqual(forwarded(events), data)
        self.assertFalse(any(event.kind == "action" for event in events))
        self.assertFalse(router.pasting)

    def test_paste_after_pending_prefix(self):
        data = b"\x07" + PASTE_START + b"text" + PASTE_END
        self.assertEqual(forwarded(self.router().feed(data, 0)), data)

    def test_key_after_paste_is_processed(self):
        events = self.router().feed(PASTE_START + b"x" + PASTE_END + b"\x07q", 0)
        self.assertEqual(events[-1], Event("action", "quit"))

    def test_printable_prefix_does_not_trigger_inside_escape_sequence(self):
        router = self.router(prefix="C")
        self.assertEqual(forwarded(router.feed(b"\x1b[C", 0)), b"\x1b[C")
        self.assertEqual(router.feed(b"Cq", 1), [Event("action", "quit")])

    def test_osc_reply_can_contain_prefix(self):
        data = b"\x1b]52;c;\x07"
        router = self.router()
        self.assertEqual(forwarded(router.feed(data, 0)), data)
        self.assertFalse(router.prefixed)

    def test_large_paste_streams_without_waiting_for_end(self):
        router = self.router()
        data = PASTE_START + b"x" * 100000
        self.assertEqual(forwarded(router.feed(data, 0)), data)
        self.assertEqual(router.buffer, b"")
        self.assertTrue(router.pasting)

    def test_enhanced_keyboard_prefix_and_action(self):
        for prefix in (b"\x1b[103;5u", b"\x1b[103;5:1u", b"\x1b[27;5;103~"):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.router().feed(prefix + b"\x1b[113u", 0), [Event("action", "quit")])

    def test_enhanced_keyboard_ordinary_input_is_preserved(self):
        data = b"\x1b[113u\x1b[99;5u\x1b[103;7u"
        self.assertEqual(forwarded(self.router().feed(data, 0)), data)

    def test_keyboard_release_event_is_not_a_prefix(self):
        router = self.router()
        data = b"\x1b[103;5:3u"
        self.assertEqual(forwarded(router.feed(data, 0)), data)
        self.assertFalse(router.prefixed)


if __name__ == "__main__":
    unittest.main()
