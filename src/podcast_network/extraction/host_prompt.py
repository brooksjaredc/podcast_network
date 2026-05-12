from __future__ import annotations

from dataclasses import dataclass

from podcast_network.extraction.prompt import truncate
from podcast_network.web.catalog.models import Podcast

PROMPT_VERSION = "podcast-host-extraction-v1"

HOST_EXTRACTION_INSTRUCTIONS = """
Extract the regular human hosts and co-hosts of a podcast from podcast-level metadata.

Rules:
- Return only regular hosts or co-hosts of the podcast, not episode guests.
- Use "host" for primary named hosts and "cohost" for regular secondary hosts,
  sidekicks, regular cast members, or recurring on-air partners.
- Do not return podcast names, networks, publishers, production companies, sponsors,
  organizations, websites, or show brands.
- Do not infer a host from a company or publisher name.
- Prefer full human names. Do not return first names, handles, initials, or nicknames
  unless the metadata itself clearly presents that as the person's public on-air name.
- In general, omit one-word names. A first name from a title like "Austin & Richard"
  is not enough evidence for a host candidate.
- If the podcast title includes named people, treat those names as strong evidence.
- If the description says "hosted by", "with", "from [person]", "host [person]",
  "co-hosted by", "joined by regular co-host", or similar podcast-level wording, treat
  that as strong evidence.
- If evidence is weak or ambiguous, omit the name.
- Use normal display casing.
- Use the evidence field for the shortest phrase that supports the classification.

Examples:
- Podcast title: "The Ezra Klein Show"; description: "Hosted by Ezra Klein."
  Return: Ezra Klein as host.

- Podcast title: "Two Ts In A Pod with Teddi Mellencamp and Tamra Judge"
  Return: Teddi Mellencamp as host, Tamra Judge as host.

- Podcast title: "The Daily"; description: "This is how the news should sound."
  Return: none unless the metadata names a regular host.

- Description: "Hosted by Sarah, with weekly producer Mike."
  Return: none for Sarah and Mike because the full human names are not provided.

- Podcast title: "2 To Ramble"; description says "Austin & Richard talk..."
  Return: none because only first names are available.
""".strip()


@dataclass(frozen=True)
class PodcastHostPrompt:
    instructions: str
    input_text: str


def build_podcast_host_prompt(podcast: Podcast) -> PodcastHostPrompt:
    apple = podcast.metadata.get("apple_podcasts") or {}
    rss = podcast.metadata.get("rss") or {}
    input_text = "\n".join(
        [
            f"Podcast title: {podcast.name}",
            f"Podcast website: {podcast.website_url}",
            f"Apple artist/publisher: {apple.get('artist_name') or ''}",
            f"RSS language: {rss.get('language') or ''}",
            "Podcast description:",
            truncate(podcast.description, 2500),
        ]
    )
    return PodcastHostPrompt(
        instructions=HOST_EXTRACTION_INSTRUCTIONS,
        input_text=input_text,
    )
