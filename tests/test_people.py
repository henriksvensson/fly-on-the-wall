import sqlite3

import pytest

from fly_on_the_wall.db import database
from fly_on_the_wall.people import create_person, get_person, list_people


def test_create_and_get_person(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        created = create_person(connection, "Person B")
        found = get_person(connection, "person_b")

    assert found == created


def test_create_person_rejects_empty_name(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        with pytest.raises(ValueError, match="cannot be empty"):
            create_person(connection, "  ")


def test_create_person_enforces_unique_display_name(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        create_person(connection, "Person B")
        with pytest.raises(sqlite3.IntegrityError):
            create_person(connection, "Person B")


def test_list_people_sorts_by_display_name(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        create_person(connection, "Zoe")
        create_person(connection, "Person B")
        people = list_people(connection)

    assert [person.display_name for person in people] == ["Person B", "Zoe"]
