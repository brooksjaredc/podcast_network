from __future__ import annotations

from dataclasses import dataclass

from podcast_network.web.catalog.models import Episode

PROMPT_VERSION = "guest-extraction-v5"

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
- Do not return hosts, co-hosts, producers, regular cast members, or recurring show
  participants unless the metadata explicitly frames them as guests for this episode.
- Do not return names from book titles, movie titles, article titles, manuals, songs,
  segment names, slogans, headlines, or sports/news topics.
- Do not return partial first names unless the metadata clearly identifies them as guests.
- Do not return roles, manuals, organizations, or non-person entities, even if capitalized.
- Title-only names are allowed only when the title is primarily a full human name, or an
  episode number followed by a full human name, and there is no evidence that the name is
  merely a topic, headline subject, book/manual author, athlete being analyzed, or host.
- Do not treat "with" as a guest cue when it means "about", "involving", "using", or
  "what happens with" a topic rather than a person present on the episode.
- If the episode appears to be a solo episode, monologue, recap, trailer, ad, or mailbag
  without named guests, return an empty guest list.
- Treat explicit guest callouts as strong evidence, including title or description labels
  like "Guest:", "Guests:", "Featuring:", "Joined by:", "Today's guest:", "Today's guests:",
  "Today's cast:", "Cast:", "Panel:", "Lineup:", or "Starred:".
- When multiple names appear in the same explicit guest/cast/panel/starred list, assign
  similar confidence to all clearly named people in that list unless a specific name is
  marked as host, producer, author/topic only, sponsor, or otherwise not present.
- For "Today's cast" or "Cast" lists, return the listed people as episode participants
  unless the metadata identifies them as regular hosts or non-person roles.
- Prefer full human names. Preserve accents and punctuation when present.
- Use the evidence field for the shortest phrase that proves the person is present.
- Never invent placeholder names or return names that only appear in these instructions.
- Use high confidence only when the evidence includes a presence cue such as "guest",
  "joined by", "talks with", "interview with", "sits down with", or "featuring".
- If the evidence does not prove presence, do not return the name.

Examples:
- Title: "Episode with Maria Lopez"
  Guests: Maria Lopez

- Description: "Host Alex talks with comedian Priya Shah about her new special."
  Guests: Priya Shah

- Title: "The Thunder Are Champions. What Is Houston's Ceiling With KD?"
  Guests: none
  Reason: KD is a topic of discussion, not identified as present.

- Title: "How to Lead and Command Ultimate Respect. With the Armed Forces Officer Manual"
  Guests: none
  Reason: this is a manual or book title, not a person guest.

- Title: "Tom and Tommy's Latest Listens"
  Guests: none
  Reason: these are title or host artifacts, not identified as guests.

- Title: "587: Johnny Pemberton"
  Guests: Johnny Pemberton
  Reason: the title is an episode number followed by a full person name.

- Title: "What Is Houston's Ceiling With KD?"
  Guests: none
  Reason: KD is an athlete being discussed as a topic, not a guest presence cue.

- Description: "The hosts discuss Trump, Cuomo, Juwan Howard, and George Floyd."
  Guests: none
  Reason: the names are discussion topics or news subjects.

- Title: "Best of the Program | Guests: Harmeet Dhillon & Carol Roth"
  Guests: Harmeet Dhillon, Carol Roth
  Reason: the title explicitly labels both names as guests.

- Description: "Today's cast: Jonathan Zaslow, Dave Dameshek, Chris Cote, Amin Elhassan."
  Guests: Jonathan Zaslow, Dave Dameshek, Chris Cote, Amin Elhassan
  Reason: all names are in the same explicit cast list, so they should receive similar confidence.

- Description: "Starred: Vincent Price, Betty Lou Gerson, Peter Leeds."
  Guests: Vincent Price, Betty Lou Gerson, Peter Leeds
  Reason: all names are in the same explicit starred list.
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
            "Episode description:",
            truncate(episode.description, 3500),
        ]
    )
    return EpisodePrompt(instructions=GUEST_EXTRACTION_INSTRUCTIONS, input_text=input_text)


def truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0] + "..."
