"""Text chunking and cleaning for TTS input."""
from __future__ import annotations

import re


def clean_markdown(text: str) -> str:
    """Strip markdown formatting, keeping plain text for TTS reading."""
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    # Strip common emoji
    text = re.sub(
        r'[\U0001f300-\U0001f9ff\u2600-\u27bf\u2300-\u23ff'
        r'\ufe0f\u200d\u20e3\u2640\u2642\u2764]+',
        '', text,
    )
    text = re.sub(r'\|[^\n]*\|', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def split_chunks(text: str, hard_limit: int = 290) -> list[str]:
    """Split text into chunks at sentence boundaries, each up to hard_limit chars.

    Splitting strategy:
    1. Split at sentence-ending punctuation (。！？…；\\n)
    2. If a sentence exceeds hard_limit, split at clause-level punctuation (，、：)
    3. If still too long, hard-split at hard_limit characters
    4. Greedy merge: combine adjacent small atoms while staying under hard_limit
    """
    raw_sentences = re.split(r"(?<=[。！？…；\n])", text.strip())
    atoms: list[str] = []
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) <= hard_limit:
            atoms.append(s)
        else:
            parts = re.split(r"(?<=[，、：])", s)
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if len(p) <= hard_limit:
                    atoms.append(p)
                else:
                    while len(p) > hard_limit:
                        atoms.append(p[:hard_limit])
                        p = p[hard_limit:]
                    if p:
                        atoms.append(p)

    chunks: list[str] = []
    current = ""
    for atom in atoms:
        if not current:
            current = atom
        elif len(current) + len(atom) <= hard_limit:
            current += atom
        else:
            chunks.append(current)
            current = atom

    if current:
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]
