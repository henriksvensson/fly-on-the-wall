from fly_on_the_wall.db import database
from fly_on_the_wall.reanalysis import list_stale_stages, mark_speaker_reanalysis_stale


def test_mark_speaker_reanalysis_stale_marks_downstream_stages(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        stages = mark_speaker_reanalysis_stale(connection, "intro")
        stale = list_stale_stages(connection)

    assert stages == ["speaker_matching", "render", "cleanup", "export"]
    assert {row["stage_name"] for row in stale} == set(stages)
