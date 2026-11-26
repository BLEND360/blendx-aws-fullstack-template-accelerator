"""Add a return address to project.toml's [auth] callback_urls without rewriting the file.

Python reads TOML but cannot write it, and a round trip through a writer would drop the file's
comments. This edits the text in place, in the forms the file can be in, and then proves the edit by
parsing it back: the new list must be the old one plus the address and nothing else may have changed.
If it cannot do that it writes nothing and says which line to add by hand.
"""

import re
import tomllib
from pathlib import Path


class ProjectTomlError(ValueError):
    pass


_AUTH = re.compile(r"^\[auth\]\s*(#.*)?$")
_SECTION = re.compile(r"^\[.*\]\s*(#.*)?$")
_KEY = re.compile(r"^(?P<indent>\s*)callback_urls\s*=\s*(?P<rest>.*)$")
_COMMENTED_KEY = re.compile(r"^\s*#\s*callback_urls\s*=")


def _callback_urls(text: str) -> list[str]:
    return list(tomllib.loads(text).get("auth", {}).get("callback_urls", []))


def _without_callback_urls(text: str) -> dict:
    data = tomllib.loads(text)
    data.get("auth", {}).pop("callback_urls", None)
    if data.get("auth") == {}:
        data.pop("auth")
    return data


def add_callback_url(path: Path, url: str) -> bool:
    """True when the file changed; False when the address was already there. Idempotent."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    found = tomllib.loads(text).get("auth", {}).get("callback_urls", [])
    if not isinstance(found, list):
        raise ProjectTomlError(_by_hand([], url, path))
    current = list(found)
    if url in current:
        return False

    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    try:
        new_text = eol.join(_edit(lines, url))
    except ProjectTomlError as e:
        raise ProjectTomlError(_by_hand(current, url, path)) from e

    # The proof: only the list grew, by exactly this address.
    try:
        ok = _callback_urls(new_text) == [*current, url] and _without_callback_urls(new_text) == _without_callback_urls(text)
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        raise ProjectTomlError(_by_hand(current, url, path))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return True


def _by_hand(current: list[str], url: str, path: Path) -> str:
    listed = ", ".join(f'"{u}"' for u in [*current, url])
    return f"Could not edit {path.name} safely. Set this line under [auth] yourself:\n  callback_urls = [{listed}]"


def _edit(lines: list[str], url: str) -> list[str]:
    start = next((i for i, line in enumerate(lines) if _AUTH.match(line.strip())), None)
    if start is None:
        body = list(lines)
        while body and body[-1] == "":
            body.pop()
        return [*body, "", "[auth]", f'callback_urls = ["{url}"]', ""]

    end = next((i for i in range(start + 1, len(lines)) if _SECTION.match(lines[i].strip())), len(lines))
    key = next((i for i in range(start + 1, end) if _KEY.match(lines[i])), None)
    if key is not None:
        return _append_to_list(lines, key, end, url)

    new_line = f'callback_urls = ["{url}"]'
    commented = next((i for i in range(start + 1, end) if _COMMENTED_KEY.match(lines[i])), None)
    if commented is not None:  # keep the example, put the real line under it
        return [*lines[: commented + 1], new_line, *lines[commented + 1 :]]
    last = max((i for i in range(start, end) if lines[i].strip()), default=start)
    return [*lines[: last + 1], new_line, *lines[last + 1 :]]


def _append_to_list(lines: list[str], key: int, end: int, url: str) -> list[str]:
    match = _KEY.match(lines[key])
    rest = match["rest"]
    if not rest.startswith("["):
        raise ProjectTomlError("callback_urls is not a list")
    new_item = f'"{url}"'

    if "]" in rest:  # the whole list is on one line
        before, after = rest.rsplit("]", 1)
        inner = before[1:].rstrip().rstrip(",").rstrip()
        joined = f"{inner}, {new_item}" if inner else new_item
        lines = list(lines)
        lines[key] = f"{match['indent']}callback_urls = [{joined}]{after}"
        return lines

    close = next((i for i in range(key + 1, end) if lines[i].split("#", 1)[0].strip().startswith("]")), None)
    if close is None:
        raise ProjectTomlError("callback_urls list is not closed")
    last_item = next((i for i in range(close - 1, key, -1) if lines[i].split("#", 1)[0].strip()), None)
    lines = list(lines)
    if last_item is None:
        indent = match["indent"] + "  "
        return [*lines[:close], f"{indent}{new_item},", *lines[close:]]
    item = lines[last_item]
    indent = item[: len(item) - len(item.lstrip())]
    code, hash_, comment = item.partition("#")
    if not code.rstrip().endswith(","):  # the last item needs a comma before another follows it
        code = code.rstrip() + ","
        lines[last_item] = code + ("  #" + comment if hash_ else "")
    return [*lines[:close], f"{indent}{new_item},", *lines[close:]]
