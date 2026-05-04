from __future__ import annotations

from dataclasses import dataclass

from podcast_network.web.catalog.models import Episode

PROMPT_VERSION = "guest-extraction-v1"

GUEST_EXTRACTION_INSTRUCTIONS = """
Extract podcast episode guest names from episode metadata.

Rules:
- Return only people who are guests, interviewees, featured guests, callers, or panelists.
- Do not return the regular podcast host unless the metadata clearly says they are a guest.
- Do not return podcast names, organizations, sponsors, book titles, topics, or fictional
  segment names.
- Do not return people who are only topics of discussion, historical figures, authors,
  politicians, celebrities, or news subjects unless the metadata says they are actually
  present as a guest, caller, interviewee, featured guest, or panelist.
- If the episode appears to be a solo episode, monologue, recap, trailer, ad, or mailbag
  without named guests, return an empty guest list.
- Prefer full human names. Preserve accents and punctuation when present.
- Use the evidence field for the shortest phrase that supports the name.
- Confidence should be 0.9+ for explicit "with Jane Doe" or "guest Jane Doe" patterns,
  lower for ambiguous names.
""".strip()


@dataclass(frozen=True)
class EpisodePrompt:
    instructions: str
    input_text: str


def build_episode_prompt(episode: Episode) -> EpisodePrompt:
    podcast = episode.podcast
    input_text = "\n".join(
        [
            f"Podcast: {podcast.name}",
            f"Episode title: {episode.title}",
            f"Published: {episode.published_at.isoformat() if episode.published_at else ''}",
            "Episode description:",
            truncate(episode.description, 3500),
        ]
    )
    return EpisodePrompt(instructions=GUEST_EXTRACTION_INSTRUCTIONS, input_text=input_text)


def truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0] + "..."
