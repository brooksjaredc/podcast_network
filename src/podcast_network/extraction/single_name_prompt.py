from __future__ import annotations

from dataclasses import dataclass

from podcast_network.extraction.prompt import EpisodePrompt, truncate
from podcast_network.web.catalog.models import Episode

PROMPT_VERSION = "guest-single-name-resolution-v1"

SINGLE_NAME_RESOLUTION_INSTRUCTIONS = """
Resolve underspecified one-word podcast guest names into full human names.

You will receive podcast episode metadata and a list of one-word names that a previous
extraction pass thought might be guests. Your job is not to re-extract every guest. Your
job is only to resolve those one-word candidates when the episode context gives enough
evidence for a full human name.

Rules:
- Return only full human names for the listed one-word candidates.
- Do not return the original one-word name unless it is truly a complete public name.
- If the context does not provide enough evidence to infer the full name, omit it.
- If the best answer would be "unknown", "full name not provided", or a note in brackets,
  omit the candidate instead.
- Do not combine two separate one-word candidates into fake full names. For example,
  if the title lists "Conway & Bruce", do not return "Conway Bruce" or "Bruce Conway"
  unless the metadata explicitly says that is a person's full name.
- Do not guess from general world knowledge unless the metadata itself strongly anchors
  the identity, such as a podcast-specific regular cast list or direct episode text.
- If the one-word candidate appears to be a host, co-host, producer, sidekick, regular
  cast member, caller nickname, social handle artifact, segment name, organization, or
  topic rather than a guest, omit it.
- If the candidate is a compact handle-like name that clearly encodes a human name,
  normalize it, for example "AutoPritts" should become "Auto Pritts".
- Use normal display casing for human names.
- Use the evidence field to explain the shortest reason the full name is supported.
- Confidence should reflect the resolution of the one-word candidate to the full name,
  not merely whether the person appears somewhere in the text.
- Most unresolved candidates should be omitted. Returning nothing is better than returning
  an unresolved nickname, handle, first name, or guessed identity.

Examples:
- Candidate: "Mike"; metadata says "Today Mike Birbiglia joins the show."
  Return: Mike Birbiglia

- Candidate: "Greg"; metadata says "Greg stops by" but gives no last name.
  Return: none

- Candidate: "AutoPritts"; podcast context clearly uses it as a person handle.
  Return: Auto Pritts

- Candidate: "EnglishNick"; metadata also says "Nick English is in studio."
  Return: Nick English

- Candidate: "TimAndrewsHere"; metadata indicates this is a recurring sidekick or
  co-host rather than an episode guest.
  Return: none
""".strip()


@dataclass(frozen=True)
class SingleNameCandidate:
    name: str
    confidence: float
    evidence: str


def build_single_name_resolution_prompt(
    episode: Episode,
    candidates: list[SingleNameCandidate],
) -> EpisodePrompt:
    input_text = "\n".join(
        [
            f"Podcast: {episode.podcast.name}",
            f"Episode title: {episode.title}",
            "One-word candidates to resolve:",
            *candidate_lines(candidates),
            "Episode description:",
            truncate(episode.description, 3500),
        ]
    )
    return EpisodePrompt(
        instructions=SINGLE_NAME_RESOLUTION_INSTRUCTIONS,
        input_text=input_text,
    )


def candidate_lines(candidates: list[SingleNameCandidate]) -> list[str]:
    return [
        (
            f"- {candidate.name} "
            f"(confidence {candidate.confidence:.2f}; evidence: {candidate.evidence})"
        )
        for candidate in candidates
    ]
