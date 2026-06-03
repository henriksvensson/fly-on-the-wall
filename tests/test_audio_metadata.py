from pathlib import Path

from fly_on_the_wall.audio_metadata import normalize_audio_metadata


def test_normalize_audio_metadata_reads_philips_tags() -> None:
    normalized = normalize_audio_metadata(
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "22050",
                    "channels": 2,
                    "channel_layout": "stereo",
                }
            ],
            "format": {
                "format_name": "mp3",
                "duration": "36.519184",
                "size": "442830",
                "bit_rate": "97007",
                "tags": {
                    "artist": "Philips VoiceTracer",
                    "title": "2026-05-11 10:07:54 Custom",
                    "genre": "Custom",
                },
            },
        },
        Path("260511_100754_00.mp3"),
    )

    assert normalized.recorded_at == "2026-05-11 10:07:54"
    assert normalized.recorded_at_source == "metadata.title"
    assert normalized.recorded_at_confidence == "high"
    assert normalized.duration_seconds == 36.519184
    assert normalized.codec == "mp3"
    assert normalized.sample_rate == 22050
    assert normalized.channels == 2
    assert normalized.metadata_artist == "Philips VoiceTracer"
    assert normalized.device_or_software == "Philips VoiceTracer"


def test_normalize_audio_metadata_reads_recup_filename_timestamp() -> None:
    normalized = normalize_audio_metadata(
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": 1,
                    "tags": {"encoder": "LAME3.99r"},
                }
            ],
            "format": {"format_name": "mp3", "duration": "38.034286", "size": "367837"},
        },
        Path("DV-2026-06-03-105536.mp3"),
    )

    assert normalized.recorded_at == "2026-06-03 10:55:36"
    assert normalized.recorded_at_source == "filename.recup"
    assert normalized.recorded_at_confidence == "medium"
    assert normalized.metadata_encoder == "LAME3.99r"
    assert normalized.device_or_software == "LAME3.99r"


def test_normalize_audio_metadata_reads_recorder_filename_timestamp() -> None:
    normalized = normalize_audio_metadata(
        {"streams": [{"codec_type": "audio"}], "format": {}},
        Path("250821_070206_00.mp3"),
    )

    assert normalized.recorded_at == "2025-08-21 07:02:06"
    assert normalized.recorded_at_source == "filename.recorder"
    assert normalized.recorded_at_confidence == "medium"
