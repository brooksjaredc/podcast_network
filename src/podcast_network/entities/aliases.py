from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownPersonAlias:
    alias_normalized_name: str
    target_normalized_name: str
    podcast_name: str = ""


KNOWN_PERSON_ALIASES = (
    KnownPersonAlias(
        alias_normalized_name="bill nye the science guy",
        target_normalized_name="bill nye",
    ),
    KnownPersonAlias(
        alias_normalized_name="neil tyson",
        target_normalized_name="neil degrasse tyson",
        podcast_name="StarTalk Radio",
    ),
    KnownPersonAlias(
        alias_normalized_name="dr joe",
        target_normalized_name="dr joe esposito",
        podcast_name="The Von Haessler Doctrine",
    ),
    KnownPersonAlias(
        alias_normalized_name="dr drew",
        target_normalized_name="dr drew pinsky",
    ),
    KnownPersonAlias(
        alias_normalized_name="christina p",
        target_normalized_name="christina pazsitzky",
    ),
    KnownPersonAlias(
        alias_normalized_name="joey coco diaz",
        target_normalized_name="joey diaz",
    ),
)
