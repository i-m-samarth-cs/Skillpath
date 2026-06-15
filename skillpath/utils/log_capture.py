"""Tee stdout/stderr into the activity bus for live Streamlit logs."""

from __future__ import annotations

import sys
from typing import TextIO

from utils.activity_bus import BUS


class _TeeStream:
    def __init__(self, original: TextIO, *, err: bool = False):
        self._original = original
        self._err = err
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._original.write(text)
        self._original.flush()
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                BUS.push_line(line)
        return len(text)

    def flush(self) -> None:
        self._original.flush()
        if self._buffer.strip():
            BUS.push_line(self._buffer.strip())
            self._buffer = ""

    def isatty(self) -> bool:
        return getattr(self._original, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")


_installed = False
_saved: tuple[TextIO, TextIO] | None = None


def install_log_capture() -> None:
    global _installed, _saved
    if _installed:
        return
    _saved = (sys.stdout, sys.stderr)
    sys.stdout = _TeeStream(sys.stdout)
    sys.stderr = _TeeStream(sys.stderr, err=True)
    _installed = True


def uninstall_log_capture() -> None:
    global _installed, _saved
    if not _installed or not _saved:
        return
    sys.stdout = _saved[0]
    sys.stderr = _saved[1]
    _installed = False
    _saved = None
