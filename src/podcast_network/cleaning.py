from __future__ import annotations

import re

NON_ENGLISH_SCRIPT_RE = re.compile(
    "["
    "\u0600-\u06ff"  # Arabic
    "\u0750-\u077f"
    "\u08a0-\u08ff"
    "\u4e00-\u9fff"  # CJK
    "\u3040-\u30ff"
    "\uac00-\ud7af"
    "]"
)
TWITTER_HANDLE_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{2,30})$")
KNOWN_COMPACT_PERSON_NAMES = {
    "autopritts": "Auto Pritts",
}


def clean_person_display_name(value: str) -> str:
    name = value.strip()
    handle = TWITTER_HANDLE_RE.match(name)
    if handle:
        name = handle.group(1).replace("_", " ")
    name = split_compact_name(name)
    name = KNOWN_COMPACT_PERSON_NAMES.get(name.casefold(), name)
    name = strip_terminal_here_token(name)
    name = strip_trailing_handle_digits(name)

    if is_all_caps_name(name):
        name = name.title()
    return " ".join(name.split())


def split_compact_name(value: str) -> str:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    return value


def strip_terminal_here_token(value: str) -> str:
    tokens = value.split()
    if len(tokens) >= 3 and tokens[-1].casefold() == "here":
        return " ".join(tokens[:-1])
    return value


def strip_trailing_handle_digits(value: str) -> str:
    tokens = value.split()
    if len(tokens) < 2:
        return value
    cleaned_last = re.sub(r"(?<=[A-Za-z])\d{1,4}$", "", tokens[-1])
    if cleaned_last and cleaned_last != tokens[-1]:
        return " ".join([*tokens[:-1], cleaned_last])
    return value


def is_all_caps_name(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return len(letters) > 2 and all(char.upper() == char for char in letters)


def is_single_token_person_name(value: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return len(tokens) < 2


def is_likely_english_podcast_name(value: str) -> bool:
    return not NON_ENGLISH_SCRIPT_RE.search(value)


def is_english_language_code(value: str) -> bool:
    normalized = value.strip().casefold().replace("_", "-")
    return not normalized or normalized == "en" or normalized.startswith("en-")
