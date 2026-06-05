from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from fly_on_the_wall.audio import AudioError
from fly_on_the_wall.cli_menu import MenuChoice, select_menu
from fly_on_the_wall.config import load_config
from fly_on_the_wall.db import database
from fly_on_the_wall.embeddings import EmbeddingBackend, PyannoteEmbeddingBackend
from fly_on_the_wall.people import Person, list_people
from fly_on_the_wall.processing import refresh_meeting
from fly_on_the_wall.reanalysis import rerun_speaker_matching_for_meetings
from fly_on_the_wall.speaker_identity import (
    create_voice_identity_from_speaker,
    prepare_speaker_review_clip,
)
from fly_on_the_wall.speakers import (
    assign_speaker_to_person,
    confirm_speaker_assignment,
    list_review_speakers,
    mark_speaker_ignored,
    speaker_examples,
)

console = Console()


@dataclass(frozen=True)
class SpeakerReviewResult:
    backend: EmbeddingBackend | None
    changed_meeting: str | None = None
    quit_review: bool = False


def speakers_review(
    meeting: Annotated[str | None, typer.Option("--meeting", "-m", help="Meeting ID or slug.")] = None,
    include_uncertain: Annotated[
        bool,
        typer.Option("--include-uncertain", help="Also review uncertain speaker matches."),
    ] = False,
    only_uncertain: Annotated[
        bool,
        typer.Option("--only-uncertain", help="Review only uncertain speaker matches."),
    ] = False,
) -> None:
    """Interactively review and assign unknown or uncertain meeting speakers."""
    backend: EmbeddingBackend | None = None
    changed_meetings: set[str] = set()
    with database() as connection:
        speakers = list_review_speakers(connection, meeting, include_uncertain, only_uncertain)
        if not speakers:
            console.print("No speakers found for review.")
            return

        for speaker in speakers:
            review = _review_one_speaker(connection, speaker, backend)
            backend = review.backend
            if review.changed_meeting is not None:
                changed_meetings.add(review.changed_meeting)
            if review.quit_review:
                break

        _refresh_reviewed_meetings(connection, changed_meetings, backend)


def _review_one_speaker(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    _print_speaker_review_prompt(connection, speaker)
    clip_path = _speaker_review_clip(connection, speaker["id"])
    while True:
        action = _select_speaker_review_action(clip_path, speaker.get("review_kind") == "uncertain")
        result = _apply_speaker_review_action(connection, speaker, action, backend)
        backend = result.backend
        if _speaker_review_action_finished(action, result):
            return result


def _speaker_review_action_finished(action: str, result: SpeakerReviewResult) -> bool:
    return result.changed_meeting is not None or result.quit_review or action == "s"


def _print_speaker_review_prompt(connection, speaker) -> None:
    console.print(f"Meeting speaker: {speaker['id']}")
    console.print(f"Meeting: {speaker['meeting_slug']}")
    console.print(f"Provider label: {speaker['label']}")
    if speaker.get("review_kind") == "uncertain":
        console.print(f"Suggested person: {speaker['suggested_person_name']}")
        if speaker.get("confidence") is not None:
            console.print(f"Confidence: {speaker['confidence']:.3f}")
        if speaker.get("margin") is not None:
            console.print(f"Margin: {speaker['margin']:.3f}")
    examples = speaker_examples(connection, speaker["id"], limit=1)
    if examples:
        console.print(f"Example: {examples[0]['text']}")


def _speaker_review_clip(connection, speaker_id: str) -> Path | None:
    try:
        clip_path = prepare_speaker_review_clip(connection, speaker_id)
    except AudioError as exc:
        console.print(f"Could not extract review clip: {exc}")
        return None
    if clip_path is not None:
        console.print(f"Clip: {clip_path}")
    return clip_path


def _apply_speaker_review_action(
    connection, speaker, action: str, backend: EmbeddingBackend | None
) -> SpeakerReviewResult:
    if action == "a":
        return _assign_with_voice_sample(connection, speaker, backend)
    if action == "n":
        return _assign_without_voice_sample(connection, speaker, backend)
    if action == "c":
        return _create_person_with_voice_sample(connection, speaker, backend)
    if action == "o":
        return _create_person_without_voice_sample(connection, speaker, backend)
    if action == "v":
        return _confirm_suggested_assignment(connection, speaker, backend)
    return _apply_non_assignment_action(connection, speaker, action, backend)


def _apply_non_assignment_action(
    connection, speaker, action: str, backend: EmbeddingBackend | None
) -> SpeakerReviewResult:
    if action == "i":
        mark_speaker_ignored(connection, speaker["id"])
        console.print("Ignored meeting speaker; it will not appear in future reviews.")
        return SpeakerReviewResult(backend, speaker["meeting_slug"])
    if action == "s":
        console.print("Skipped.")
        return SpeakerReviewResult(backend)
    if action == "q":
        console.print("Review cancelled.")
        return SpeakerReviewResult(backend, quit_review=True)
    console.print("Choose an available action.")
    return SpeakerReviewResult(backend)


def _assign_with_voice_sample(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    person = _select_person(connection)
    if person is None:
        console.print("Assignment cancelled.")
        return SpeakerReviewResult(backend)
    backend = backend or _try_embedding_backend()
    try:
        result = create_voice_identity_from_speaker(connection, speaker["id"], person.id, storage=None, backend=backend)
    except ValueError as exc:
        console.print(str(exc))
        return SpeakerReviewResult(backend)
    console.print(f"Assigned meeting speaker to {result.person_name}")
    console.print(f"Voice sample: {result.voice_sample.audio_path}")
    return SpeakerReviewResult(backend, speaker["meeting_slug"])


def _assign_without_voice_sample(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    person = _select_person(connection)
    if person is None:
        console.print("Assignment cancelled.")
        return SpeakerReviewResult(backend)
    assignment = assign_speaker_to_person(connection, speaker["id"], person.id)
    console.print(f"Assigned meeting speaker to {assignment['name']} without voice sample.")
    return SpeakerReviewResult(backend, speaker["meeting_slug"])


def _create_person_with_voice_sample(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    name = typer.prompt("New known person name")
    backend = backend or _try_embedding_backend()
    try:
        result = create_voice_identity_from_speaker(
            connection,
            speaker["id"],
            name,
            create_missing_person=True,
            storage=None,
            backend=backend,
        )
    except ValueError as exc:
        console.print(str(exc))
        return SpeakerReviewResult(backend)
    console.print(f"Created known person {result.person_name}")
    console.print(f"Voice sample: {result.voice_sample.audio_path}")
    return SpeakerReviewResult(backend, speaker["meeting_slug"])


def _create_person_without_voice_sample(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    name = typer.prompt("New known person name")
    assignment = assign_speaker_to_person(connection, speaker["id"], name)
    console.print(f"Created known person {assignment['name']}")
    console.print(f"Assigned meeting speaker to {assignment['name']} without voice sample.")
    return SpeakerReviewResult(backend, speaker["meeting_slug"])


def _confirm_suggested_assignment(connection, speaker, backend: EmbeddingBackend | None) -> SpeakerReviewResult:
    suggested_person_id = speaker.get("suggested_person_id")
    suggested_person_name = speaker.get("suggested_person_name")
    if not suggested_person_id:
        console.print("No suggested person available for this speaker.")
        return SpeakerReviewResult(backend)

    backend = backend or _try_embedding_backend()
    try:
        result = create_voice_identity_from_speaker(connection, speaker["id"], suggested_person_id, backend=backend)
    except ValueError as exc:
        console.print(f"Could not create voice sample ({exc}); confirming assignment only.")
        assignment = confirm_speaker_assignment(connection, speaker["id"])
        console.print(f"Confirmed meeting speaker as {assignment['name']}.")
        return SpeakerReviewResult(backend, speaker["meeting_slug"])

    console.print(f"Confirmed meeting speaker as {suggested_person_name or result.person_name}.")
    console.print(f"Voice sample: {result.voice_sample.audio_path}")
    return SpeakerReviewResult(backend, speaker["meeting_slug"])


def _refresh_reviewed_meetings(connection, changed_meetings: set[str], backend: EmbeddingBackend | None) -> None:
    if not changed_meetings:
        return
    refresh_meetings = _speaker_review_follow_up(connection, changed_meetings)
    if not refresh_meetings:
        return
    config = load_config()
    for meeting_slug in sorted(refresh_meetings):
        result = refresh_meeting(
            connection,
            meeting_slug,
            config,
            embedding_backend=backend,
            progress=lambda message: console.print(f"-> {message}"),
        )
        console.print(f"Refreshed {result.meeting.slug}")
        console.print(f"Transcript: {result.export.transcript_path}")
        console.print(f"Analysis: {result.export.analysis_path}")


def _speaker_review_follow_up(connection, changed_meetings: set[str]) -> set[str]:
    console.print(f"Speaker review changed {len(changed_meetings)} meeting(s).")
    while True:
        action = _select_speaker_review_follow_up_action()
        if action == "a":
            return set(changed_meetings)
        if action == "g":
            return _speaker_review_global_follow_up(connection, changed_meetings)
        if action == "n":
            console.print("Refresh skipped. You can run refresh later.")
            return set()
        console.print("Choose an available follow-up action.")


def _speaker_review_global_follow_up(connection, changed_meetings: set[str]) -> set[str]:
    results = rerun_speaker_matching_for_meetings(connection)
    refreshed = {result["meeting_slug"] for result in results if result["match_count"]}
    if not refreshed:
        console.print("No new speaker matches found in other meetings.")
        return set(changed_meetings)
    console.print(f"Refreshed speaker matching with new matches: {len(refreshed)}")
    return set(changed_meetings) | refreshed


def _try_embedding_backend() -> EmbeddingBackend | None:
    try:
        return PyannoteEmbeddingBackend()
    except RuntimeError as exc:
        console.print(f"Voice sample saved without embedding ({exc})")
        return None


def _select_person(connection) -> Person | None:
    people = list_people(connection)
    if not people:
        console.print("No known people found. Create a known person instead.")
        return None

    choices = [
        MenuChoice(str(index) if index <= 9 else None, person.display_name, person.id)
        for index, person in enumerate(people, start=1)
    ]
    choices.append(MenuChoice("c", "Cancel", None))
    selected_person_id = select_menu("Known person", choices)
    if selected_person_id is None:
        return None
    return next(person for person in people if person.id == selected_person_id)


def _select_speaker_review_action(clip_path: Path | None, can_confirm: bool = False) -> str:
    choices = []
    if clip_path is not None:
        choices.append(MenuChoice("p", "Play clip", None, playback_path=clip_path))
    if can_confirm:
        choices.append(MenuChoice("v", "Confirm suggested person", "v"))
    choices.extend(
        [
            MenuChoice("a", "Assign with voice sample", "a"),
            MenuChoice("n", "Assign only", "n"),
            MenuChoice("c", "New known person with voice sample", "c"),
            MenuChoice("o", "New known person only", "o"),
            MenuChoice("i", "Ignore speaker forever", "i"),
            MenuChoice("s", "Skip this time", "s"),
            MenuChoice("q", "Quit review", "q"),
        ]
    )
    return select_menu("Action", choices) or "q"


def _select_speaker_review_follow_up_action() -> str:
    choices = [
        MenuChoice("a", "Refresh affected meetings", "a"),
        MenuChoice("g", "Refresh speaker matching globally", "g"),
        MenuChoice("n", "Do nothing", "n"),
    ]
    return select_menu("Next", choices) or "n"
