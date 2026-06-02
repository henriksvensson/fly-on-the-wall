from __future__ import annotations

import re


def deterministic_cleanup(transcript: str) -> str:
    turns = [_parse_turn(line) for line in transcript.splitlines() if line.strip()]
    merged: list[tuple[str, str]] = []
    for speaker, text in turns:
        cleaned_text = normalize_whitespace(text)
        if not cleaned_text:
            continue
        if merged and merged[-1][0] == speaker:
            previous_speaker, previous_text = merged[-1]
            merged[-1] = (previous_speaker, normalize_whitespace(f"{previous_text} {cleaned_text}"))
        else:
            merged.append((speaker, cleaned_text))
    return "\n\n".join(f"{speaker}: {text}" for speaker, text in merged)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_turn(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "Unknown", line
    speaker, text = line.split(":", 1)
    return normalize_whitespace(speaker), text
