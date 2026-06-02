from fly_on_the_wall.cleanup import deterministic_cleanup, normalize_whitespace


def test_normalize_whitespace_collapses_spaces() -> None:
    assert normalize_whitespace(" hej\n  där ") == "hej där"


def test_deterministic_cleanup_merges_adjacent_same_speaker_turns() -> None:
    transcript = """
Person B [sv] (speaker_0): Hej

Person B [sv] (speaker_0): där

Bob [sv] (speaker_1): Hallå
"""

    cleaned = deterministic_cleanup(transcript)

    assert cleaned == "Person B [sv] (speaker_0): Hej där\n\nBob [sv] (speaker_1): Hallå"


def test_deterministic_cleanup_does_not_merge_different_speaker_turns() -> None:
    transcript = "Person B: Hej\n\nBob: Hallå\n\nPerson B: Igen"

    assert deterministic_cleanup(transcript) == transcript
