import sqlite3

import pytest

from fly_on_the_wall.db import database
from fly_on_the_wall.people import (
    create_person,
    get_person,
    get_user_person,
    list_people,
    set_user_person,
    unset_user_person,
)


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


def test_set_user_person_keeps_only_one_user(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        person_b = create_person(connection, "Person B")
        person_a = create_person(connection, "Person A")
        first = set_user_person(connection, person_b.id)
        second = set_user_person(connection, "Person A")
        people = list_people(connection)

    assert first.is_user
    assert second.id == person_a.id
    assert second.display_name == "Person A"
    assert second.is_user
    assert [person.display_name for person in people if person.is_user] == ["Person A"]


def test_get_and_unset_user_person(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        create_person(connection, "Person A")
        set_user_person(connection, "Person A")
        user = get_user_person(connection)
        cleared = unset_user_person(connection)
        after_clear = get_user_person(connection)

    assert user is not None
    assert user.display_name == "Person A"
    assert cleared is not None
    assert not cleared.is_user
    assert after_clear is None
