"""Per-session automatic restart budget using a rolling time window."""

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Session:
    pid: str = ""
    dead_since: float | None = None
    attempts: deque = field(default_factory=deque)
    failed: bool = False
    restarting: bool = False


class Restarts:
    def __init__(self, limit: int, window: float, delay: float):
        self.limit, self.window, self.delay = limit, window, delay
        self.sessions: dict[str, Session] = {}

    @property
    def has_failures(self) -> bool:
        return any(session.failed for session in self.sessions.values())

    def observe(self, window: str, pid: str, dead: bool, now: float) -> str | None:
        session = self.sessions.setdefault(window, Session())
        if session.pid != pid:
            was_failed = session.failed
            session.pid, session.dead_since = pid, None
            session.restarting = False
            if was_failed:  # A manual restart retries a failed session with a fresh budget.
                session.failed = False
                session.attempts.clear()
                return "reset"
        if not dead:
            session.dead_since = None
            return None
        if session.failed or session.restarting:
            return None
        if session.dead_since is None:
            session.dead_since = now
        if now - session.dead_since < self.delay:
            return None
        while session.attempts and now - session.attempts[0] >= self.window:
            session.attempts.popleft()
        session.attempts.append(now)
        if len(session.attempts) >= self.limit:
            session.failed = True
            return "failed"
        session.dead_since = None
        session.restarting = True
        return "restart"
