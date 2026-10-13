"""Incremental input routing, without decoding or rewriting application input."""

from dataclasses import dataclass
import re


NAMED_KEYS = {
    "Left": (b"\x1b[D", b"\x1bOD"),
    "Right": (b"\x1b[C", b"\x1bOC"),
    "Up": (b"\x1b[A", b"\x1bOA"),
    "Down": (b"\x1b[B", b"\x1bOB"),
    "Home": (b"\x1b[H", b"\x1bOH", b"\x1b[1~", b"\x1b[7~"),
    "End": (b"\x1b[F", b"\x1bOF", b"\x1b[4~", b"\x1b[8~"),
    "PageUp": (b"\x1b[5~",),
    "PageDown": (b"\x1b[6~",),
    "Space": (b" ",),
    "Tab": (b"\t",),
    "Enter": (b"\r",),
    "Backspace": (b"\x7f", b"\x08"),
    "Escape": (b"\x1b",),
}
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"


def key_sequences(name: str) -> tuple[bytes, ...]:
    if name in NAMED_KEYS:
        return NAMED_KEYS[name]
    if len(name) == 3 and name[:2].lower() == "c-":
        char = name[2].upper()
        if "@" <= char <= "_":
            return (bytes([ord(char) & 31]),)
        if char == "?":
            return (b"\x7f",)
    if len(name) == 1 and 32 <= ord(name) <= 126:
        return (name.encode("ascii"),)
    raise ValueError(f"unsupported key {name!r}; use C-g, Left, Space, or an ASCII character")


def prefix_sequence(name: str) -> bytes:
    sequences = key_sequences(name)
    if len(sequences) != 1 or len(sequences[0]) != 1 or sequences[0] == b"\x1b":
        raise ValueError("prefix must be one ASCII character or a control key such as C-g")
    return sequences[0]


def normalized_key(token: bytes) -> bytes:
    """Recognize ASCII keys encoded by CSI-u or xterm modifyOtherKeys.

    Keep the original bytes for forwarding; normalization is only for matching
    the carousel's prefix and actions. Release events are never action keys.
    """
    kitty = re.fullmatch(rb"\x1b\[(\d+)(?:;(\d+)(?::([123]))?)?u", token)
    xterm = re.fullmatch(rb"\x1b\[27;(\d+);(\d+)~", token)
    if kitty:
        if kitty[3] == b"3":
            return token
        code, modifiers = int(kitty[1]), int(kitty[2] or b"1")
    elif xterm:
        modifiers, code = int(xterm[1]), int(xterm[2])
    else:
        return token
    if modifiers == 1 and 0 <= code < 128:
        return bytes([code])
    if modifiers == 5 and code in (32, 64):
        return b"\x00"
    if modifiers == 5 and (65 <= code <= 95 or 97 <= code <= 122):
        return bytes([code & 31])
    return token


@dataclass(frozen=True)
class Event:
    kind: str
    value: bytes | str


class InputRouter:
    """Recognize keys across reads; keep pasted text and escape strings intact."""

    def __init__(self, prefix: bytes, bindings: dict[bytes, str], escape_timeout: float = 0.1):
        self.prefix = prefix
        self.bindings = bindings
        self.escape_timeout = escape_timeout
        self.buffer = b""
        self.prefixed = False
        self.pasting = False
        self.escape_since: float | None = None

    def feed(self, data: bytes, now: float) -> list[Event]:
        self.buffer += data
        events: list[Event] = []
        while self.buffer:
            if self.pasting:
                end = self.buffer.find(PASTE_END)
                if end >= 0:
                    count = end + len(PASTE_END)
                    events.append(Event("data", self.buffer[:count]))
                    self.buffer = self.buffer[count:]
                    self.pasting = False
                    continue
                # Keep only a possible split end marker, never the entire paste.
                keep = 0
                for size in range(1, min(len(self.buffer), len(PASTE_END) - 1) + 1):
                    if self.buffer.endswith(PASTE_END[:size]):
                        keep = size
                count = len(self.buffer) - keep
                if count:
                    events.append(Event("data", self.buffer[:count]))
                    self.buffer = self.buffer[count:]
                break
            count = self._token_length(now)
            if count is None:
                break
            token, self.buffer = self.buffer[:count], self.buffer[count:]
            self.escape_since = None
            key = normalized_key(token)
            if token == PASTE_START:
                self.pasting = True
                if self.prefixed:
                    events.append(Event("literal_prefix", self.prefix))
                events.append(Event("data", token))
                self.prefixed = False
            elif self.prefixed:
                self.prefixed = False
                if key == self.prefix:
                    events.append(Event("literal_prefix", self.prefix))
                elif key in self.bindings:
                    events.append(Event("action", self.bindings[key]))
                else:
                    events.append(Event("literal_prefix", self.prefix))
                    events.append(Event("data", token))
            elif key == self.prefix:
                self.prefixed = True
            else:
                events.append(Event("data", token))
        # Coalesce adjacent byte events so large pastes don't produce tiny writes.
        merged: list[Event] = []
        for event in events:
            if event.kind == "data" and merged and merged[-1].kind == "data":
                merged[-1] = Event("data", merged[-1].value + event.value)
            else:
                merged.append(event)
        return merged

    def _token_length(self, now: float) -> int | None:
        data = self.buffer
        if data[0] != 27:
            if self.prefixed or data[:1] == self.prefix:
                return 1
            boundaries = [i for i in (data.find(b"\x1b"), data.find(self.prefix)) if i >= 0]
            return min(boundaries) if boundaries else len(data)
        if self.escape_since is None:
            self.escape_since = now
        count = None
        if len(data) >= 2:
            if data[1:2] == b"[":  # CSI: arrows, terminal replies, paste markers.
                count = next((i + 1 for i in range(2, len(data)) if 64 <= data[i] <= 126), None)
            elif data[1:2] == b"O":  # Application cursor keys.
                count = 3 if len(data) >= 3 else None
            elif data[1:2] in (b"]", b"P", b"_", b"^", b"X"):
                stops = [i + 2 for i in [data.find(b"\x1b\\", 2)] if i >= 0]
                if data[1:2] == b"]" and b"\x07" in data[2:]:
                    stops.append(data.index(b"\x07", 2) + 1)
                count = min(stops) if stops else None
            else:
                count = 2  # Alt-key or a simple escape sequence.
        if count is not None:
            return count
        if len(data) > 4096 or now - self.escape_since >= self.escape_timeout:
            # Preserve incomplete sequences; a solitary Escape is also a key.
            return len(data)
        return None
