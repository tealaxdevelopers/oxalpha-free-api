"""Minimal, dependency-free Server-Sent Events parser.

Handles: events split across arbitrary chunk boundaries, multi-byte UTF-8
characters split between chunks, CRLF / LF / CR line endings, multi-line
``data:`` fields, ``data:`` without a trailing space, comments, and a final
event that is not terminated by a blank line.
"""
import codecs
import re
from typing import Any, Dict, List, Union

_LINE_SPLIT = re.compile(r"\r\n|\n|\r")


class SSEParser:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""
        self._data: List[str] = []
        self._event: Union[str, None] = None

    def _line(self, line: str, out: List[Dict[str, Any]]) -> None:
        if line == "":
            self._dispatch(out)
            return
        if line.startswith(":"):
            return  # comment / keep-alive
        field, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if field == "data":
            self._data.append(value)
        elif field == "event":
            self._event = value

    def _dispatch(self, out: List[Dict[str, Any]]) -> None:
        if self._data:
            out.append({"event": self._event or "message", "data": "\n".join(self._data)})
        self._data = []
        self._event = None

    def feed(self, chunk: Union[bytes, str]) -> List[Dict[str, Any]]:
        text = self._decoder.decode(chunk) if isinstance(chunk, (bytes, bytearray)) else chunk
        buf = self._buf + text
        hold = ""
        if buf.endswith("\r"):  # may be the first half of \r\n
            hold, buf = "\r", buf[:-1]
        parts = _LINE_SPLIT.split(buf)
        self._buf = parts.pop() + hold
        out: List[Dict[str, Any]] = []
        for line in parts:
            self._line(line, out)
        return out

    def finish(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        tail = self._decoder.decode(b"", final=True)
        buf = self._buf + tail
        self._buf = ""
        for line in _LINE_SPLIT.split(buf):
            if line:
                self._line(line, out)
        self._dispatch(out)  # lenient: flush an unterminated last event
        return out
