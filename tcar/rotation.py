"""Rotation uses keyboard activity, never output from a busy monitor."""


class Rotation:
    def __init__(self, idle_timeout: float, interval: float, enabled: bool, now: float):
        self.idle_timeout = idle_timeout
        self.interval = interval
        self.enabled = enabled
        self.rotating = False
        self.next_at = now + idle_timeout

    @property
    def mode(self) -> str:
        return "paused" if not self.enabled else "rotating" if self.rotating else "idle wait"

    def activity(self, now: float, manual_switch: bool = False) -> None:
        self.rotating = False
        self.next_at = now + max(self.idle_timeout, self.interval if manual_switch else 0)

    def toggle(self, now: float) -> None:
        self.enabled = not self.enabled
        self.rotating = self.enabled
        self.next_at = now + self.interval

    def tick(self, now: float) -> bool:
        if not self.enabled or now < self.next_at:
            return False
        self.rotating = True
        self.next_at = now + self.interval
        return True
