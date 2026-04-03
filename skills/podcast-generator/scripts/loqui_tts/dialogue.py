"""Dialogue script parsing — split role-tagged text into (voice, chunk) pairs."""
from __future__ import annotations

import re
from .chunker import split_chunks


def parse_dialogue(
    text: str,
    role_names: list[str] | None = None,
    default_voice: str = "",
) -> list[tuple[str, str]]:
    """Parse role-tagged script into [(voice_name, chunk_text), ...].

    Format: 【RoleName】speech text

    Each role's speech is further split into TTS-friendly chunks
    (up to 290 characters at sentence boundaries).

    Args:
        text: Full script text with role tags.
        role_names: List of valid role names to parse. If None, matches any
                    characters inside 【】.
        default_voice: Voice name to use for untagged text.

    Returns:
        List of (voice_name, chunk_text) tuples.
    """
    if role_names:
        pattern = '【(' + '|'.join(re.escape(n) for n in role_names) + ')】'
    else:
        pattern = r'【([^】]+)】'

    parts = re.split(pattern, text)

    segments: list[tuple[str, str]] = []

    if len(parts) < 3:
        # No role tags found — use default voice for everything
        chunks = split_chunks(text)
        return [(default_voice, c) for c in chunks]

    # parts[0] = text before first tag (usually empty)
    if parts[0].strip():
        chunks = split_chunks(parts[0].strip())
        segments.extend((default_voice, c) for c in chunks)

    # parts[1], parts[2], ... = role, speech, role, speech, ...
    for i in range(1, len(parts), 2):
        voice = parts[i]
        speech = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not speech:
            continue
        chunks = split_chunks(speech)
        segments.extend((voice, c) for c in chunks)

    return segments
