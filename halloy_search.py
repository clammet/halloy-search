#!/usr/bin/env python3.14
"""Search Halloy IRC log history.

Halloy stores history as flat, hash-named files in its history directory:
  - ``<hash>.json``     read-marker metadata (ignored)
  - ``<hash>.json.gz``  one buffer's messages (a channel, query/DM, or server
                        buffer) as a JSON array of message objects

This tool walks every message file, renders each message as
``<nick> text`` (or a server/status line), and greps the rendered lines,
optionally printing context lines above/below each hit like grep -A/-B/-C.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_DIR = Path.home() / "Library/Application Support/halloy/history"

# ANSI styles (emptied out when color is disabled)
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"


@dataclass(frozen=True)
class Message:
    """One rendered log line."""

    timestamp: datetime | None
    line: str  # e.g. "<clam> hello there" or "-!- pono quit"

    def format(self, color: bool) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "????-??-?? ??:??:??"
        if color:
            return f"{DIM}{ts}{RESET}  {self.line}"
        return f"{ts}  {self.line}"


@dataclass(frozen=True)
class Buffer:
    """One history file: its buffer name plus all rendered messages."""

    name: str  # "#channel", "nick" (query), or "<server>"
    path: Path
    messages: list[Message]


def parse_timestamp(raw: dict[str, Any]) -> datetime | None:
    server_time = raw.get("server_time")
    if isinstance(server_time, str):
        try:
            return datetime.fromisoformat(server_time).astimezone()
        except ValueError:
            pass
    received_at = raw.get("received_at")
    if isinstance(received_at, (int, float)):
        # received_at is nanoseconds since the epoch
        return datetime.fromtimestamp(received_at / 1e9, tz=timezone.utc).astimezone()
    return None


def nick_from_user_mask(mask: str) -> str:
    """'@ clam!~clam@host' -> 'clam' (leading part is channel-mode prefixes)."""
    _, _, tail = mask.rpartition(" ")
    nick, _, _ = tail.partition("!")
    return nick or mask


def extract_source(target: dict[str, Any]) -> dict[str, Any] | None:
    for variant in target.values():
        if isinstance(variant, dict):
            source = variant.get("source")
            if isinstance(source, dict):
                return source
    return None


def render_sender(raw: dict[str, Any]) -> str:
    target = raw.get("target")
    source = extract_source(target) if isinstance(target, dict) else None
    if source is None:
        return "***"
    user = source.get("User")
    if isinstance(user, str):
        return f"<{nick_from_user_mask(user)}>"
    if "Action" in source:
        return "*"
    if "Server" in source:
        return "-!-"
    return "***"  # Internal status lines


def buffer_name(target: dict[str, Any]) -> str | None:
    """Channel / query name from a message target; None for server buffers."""
    channel = target.get("Channel")
    if isinstance(channel, dict):
        info = channel.get("channel")
        if isinstance(info, dict) and isinstance(info.get("raw"), str):
            return str(info["raw"])
    query = target.get("Query")
    if isinstance(query, dict):
        info = query.get("query")
        if isinstance(info, dict) and isinstance(info.get("raw"), str):
            return str(info["raw"])
    return None


def load_buffer(path: Path) -> Buffer | None:
    """Load one history file; returns None for metadata files / unreadable data."""
    try:
        if path.name.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                data: Any = json.load(fh)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None  # read-marker metadata dict

    name: str | None = None
    messages: list[Message] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            continue
        target = raw.get("target")
        if name is None and isinstance(target, dict):
            name = buffer_name(target)
        messages.append(Message(parse_timestamp(raw), f"{render_sender(raw)} {text}"))
    if not messages:
        return None
    return Buffer(name or "<server>", path, messages)


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def search_buffer(
    buf: Buffer,
    pattern: re.Pattern[str],
    before: int,
    after: int,
    color: bool,
) -> tuple[int, list[str]]:
    """Return (match_count, output_lines) for one buffer."""
    hits = [i for i, msg in enumerate(buf.messages) if pattern.search(msg.line)]
    if not hits:
        return 0, []

    last = len(buf.messages) - 1
    groups = merge_intervals([(max(0, i - before), min(last, i + after)) for i in hits])
    hit_set = set(hits)

    out: list[str] = []
    if color:
        out.append(f"{BOLD}{CYAN}{buf.name}{RESET} {DIM}({buf.path.name}){RESET}")
    else:
        out.append(f"{buf.name} ({buf.path.name})")
    for gi, (start, end) in enumerate(groups):
        if gi > 0:
            out.append(f"{DIM}--{RESET}" if color else "--")
        for i in range(start, end + 1):
            line = buf.messages[i].format(color)
            if i in hit_set and color:
                line = pattern.sub(lambda m: f"{BOLD}{RED}{m.group(0)}{RESET}", line)
            out.append(line)
    return len(hits), out


def build_pattern(args: argparse.Namespace) -> re.Pattern[str]:
    term: str = re.escape(args.term) if args.fixed_string else args.term
    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        return re.compile(term, flags)
    except re.error as exc:
        sys.exit(f"error: invalid regex {args.term!r}: {exc} (use -F for a literal search)")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Halloy IRC log history.",
        epilog="Matching runs against the rendered line ('<nick> text'), so nicks are searchable too.",
    )
    parser.add_argument("term", help="search term (a regex unless -F is given)")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="case-insensitive matching")
    parser.add_argument("-F", "--fixed-string", action="store_true", help="treat the term as a literal string, not a regex")
    parser.add_argument("-A", "--after", type=int, default=0, metavar="N", help="show N lines after each match")
    parser.add_argument("-B", "--before", type=int, default=0, metavar="N", help="show N lines before each match")
    parser.add_argument("-C", "--context", type=int, default=0, metavar="N", help="show N lines before and after each match")
    parser.add_argument("-b", "--buffer", metavar="NAME", help="only search buffers whose name contains NAME (e.g. '#chan' or a nick), case-insensitive")
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR, metavar="PATH", help=f"halloy history directory (default: {DEFAULT_HISTORY_DIR})")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    args = parser.parse_args(argv)
    args.after = max(args.after, args.context)
    args.before = max(args.before, args.context)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pattern = build_pattern(args)
    color = sys.stdout.isatty() and not args.no_color

    history_dir: Path = args.history_dir
    if not history_dir.is_dir():
        sys.exit(f"error: history directory not found: {history_dir}")

    buffers: list[Buffer] = []
    for path in sorted(history_dir.iterdir()):
        if path.suffix not in (".json", ".gz"):
            continue
        buf = load_buffer(path)
        if buf is None:
            continue
        if args.buffer and args.buffer.lower() not in buf.name.lower():
            continue
        buffers.append(buf)
    buffers.sort(key=lambda b: b.name.lower())

    total = 0
    matched_buffers = 0
    first = True
    for buf in buffers:
        count, lines = search_buffer(buf, pattern, args.before, args.after, color)
        if not count:
            continue
        total += count
        matched_buffers += 1
        if not first:
            print()
        first = False
        print("\n".join(lines))

    summary = f"{total} match{'es' if total != 1 else ''} in {matched_buffers} buffer{'s' if matched_buffers != 1 else ''}"
    print(f"\n{DIM}{summary}{RESET}" if color else f"\n{summary}", file=sys.stderr)
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
