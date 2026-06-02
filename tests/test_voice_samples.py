from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.people import create_person
from fly_on_the_wall.storage import ensure_storage_layout
from fly_on_the_wall.voice_samples import (
    create_voice_sample_from_clip,
    create_voice_sample_from_span,
    list_voice_samples,
)


def test_create_voice_sample_from_clip_copies_file(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"voice")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        person = create_person(connection, "Person B")
        sample = create_voice_sample_from_clip(connection, person.id, clip_path, storage)
        samples = list_voice_samples(connection, person.id)

    assert sample.audio_path.read_bytes() == b"voice"
    assert samples == [sample]


def test_create_voice_sample_from_span_extracts_clip(tmp_path: Path, monkeypatch) -> None:
    source_audio_path = tmp_path / "meeting.m4a"
    source_audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    calls: list[tuple[Path, Path, float, float]] = []

    def fake_extract(input_path: Path, output_path: Path, start: float, end: float) -> Path:
        calls.append((input_path, output_path, start, end))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return output_path

    monkeypatch.setattr("fly_on_the_wall.voice_samples.extract_clip", fake_extract)

    with database(tmp_path / "fly.db") as connection:
        person = create_person(connection, "Person B")
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting-1", "Meeting", "sv"),
        )
        sample = create_voice_sample_from_span(
            connection,
            person.id,
            source_audio_path,
            "meeting-1",
            None,
            1.0,
            4.0,
            storage,
        )

    assert calls == [(source_audio_path, sample.audio_path, 1.0, 4.0)]
    assert sample.audio_path.read_bytes() == b"clip"
    assert sample.source_meeting_id == "meeting-1"
    assert sample.start_time == 1.0
    assert sample.end_time == 4.0
