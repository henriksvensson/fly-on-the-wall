from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import get_meeting, list_meetings, meeting_stage_status
from fly_on_the_wall.pipeline import set_stage_status


def test_list_and_get_meetings(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        meetings = list_meetings(connection)
        meeting = get_meeting(connection, "intro")

    assert meetings[0]["slug"] == "intro"
    assert meeting["title"] == "Intro"


def test_meeting_stage_status_returns_stage_rows(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        set_stage_status(connection, "meeting-1", "import", "done")
        stages = meeting_stage_status(connection, "intro")

    assert stages == [
        {
            "stage_name": "import",
            "status": "done",
            "error_message": None,
            "updated_at": stages[0]["updated_at"],
        }
    ]
