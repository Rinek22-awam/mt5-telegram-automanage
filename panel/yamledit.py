"""Change single values in config.yaml without touching its comments or layout."""
import json
import re
from typing import Sequence

_KEY = re.compile(r"^(\s*)([^\s#\-][^:#]*?):([ \t]*)(.*)$")


def fmt(value) -> str:
    """Python value -> YAML text as written in config.yaml."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(fmt(v) for v in value) + "]"
    s = str(value)
    plain = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]*", s) and s.lower() not in (
        "true", "false", "null", "yes", "no", "on", "off", "y", "n")
    return s if plain else json.dumps(s)


def _split_comment(rest: str):
    """'1.0     # text' -> ('1.0', 7 spaces + '# text'). Values here never contain ' #'."""
    m = re.search(r"\s+#", rest)
    return (rest, "") if not m else (rest[:m.start()], rest[m.start():])


def _walk(lines):
    """Yield (index, path, match) for every 'key: value' line."""
    stack = []
    for i, line in enumerate(lines):
        m = _KEY.match(line.rstrip("\r\n"))
        if not m:
            continue
        indent, key = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        yield i, tuple(k for _, k in stack) + (key,), m
        stack.append((indent, key))


def set_value(text: str, path: Sequence[str], value) -> str:
    lines = text.splitlines(keepends=True)
    path = tuple(str(p) for p in path)
    for i, p, m in _walk(lines):
        if p != path:
            continue
        old, comment = _split_comment(m.group(4))
        prefix = f"{m.group(1)}{m.group(2)}:{m.group(3) or ' '}"
        head = prefix + fmt(value)
        if comment:   # keep the comment in its column when the new value fits
            text_part = comment.lstrip(" \t")
            col = len(prefix) + len(old) + len(comment) - len(text_part)
            head = head.ljust(col) + text_part if len(head) < col else f"{head} {text_part}"
        end = lines[i][len(lines[i].rstrip("\r\n")):]
        lines[i] = head + end
        return "".join(lines)
    raise KeyError(".".join(path))


def add_value(text: str, parent: Sequence[str], key: str, value) -> str:
    """Add 'key: value' as the last child of `parent` (which must have children)."""
    lines = text.splitlines(keepends=True)
    parent = tuple(str(p) for p in parent)
    last, indent = None, None
    for i, p, m in _walk(lines):
        if p[:-1] == parent:
            last, indent = i, m.group(1)
    if last is None:
        raise KeyError(".".join(parent))
    end = lines[last][len(lines[last].rstrip("\r\n")):] or "\n"
    lines.insert(last + 1, f"{indent}{fmt(key)}: {fmt(value)}{end}")
    return "".join(lines)


def remove_value(text: str, path: Sequence[str]) -> str:
    lines = text.splitlines(keepends=True)
    path = tuple(str(p) for p in path)
    for i, p, _ in _walk(lines):
        if p == path:
            del lines[i]
            return "".join(lines)
    raise KeyError(".".join(path))
