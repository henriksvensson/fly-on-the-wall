from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from uuid import uuid4


@dataclass(frozen=True)
class Person:
    id: str
    display_name: str
    is_user: bool = False


def create_person(connection: Connection, display_name: str) -> Person:
    person = Person(id=str(uuid4()), display_name=display_name.strip(), is_user=False)
    if not person.display_name:
        raise ValueError("Person display name cannot be empty.")

    with connection:
        connection.execute(
            "INSERT INTO people(id, display_name) VALUES (?, ?)",
            (person.id, person.display_name),
        )
    return person


def list_people(connection: Connection) -> list[Person]:
    rows = connection.execute("SELECT id, display_name, is_user FROM people ORDER BY display_name").fetchall()
    return [_person_from_row(row) for row in rows]


def get_person(connection: Connection, person_id_or_name: str) -> Person | None:
    row = connection.execute(
        """
        SELECT id, display_name, is_user FROM people
        WHERE id = ? OR lower(display_name) = lower(?)
        """,
        (person_id_or_name, person_id_or_name),
    ).fetchone()
    if row is None:
        return None
    return _person_from_row(row)


def get_user_person(connection: Connection) -> Person | None:
    row = connection.execute("SELECT id, display_name, is_user FROM people WHERE is_user = 1 LIMIT 1").fetchone()
    return None if row is None else _person_from_row(row)


def set_user_person(connection: Connection, person_id_or_name: str) -> Person:
    person = get_person(connection, person_id_or_name)
    if person is None:
        raise ValueError(f"Person not found: {person_id_or_name}")

    with connection:
        connection.execute("UPDATE people SET is_user = 0")
        connection.execute(
            "UPDATE people SET is_user = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (person.id,),
        )
    return Person(id=person.id, display_name=person.display_name, is_user=True)


def unset_user_person(connection: Connection) -> Person | None:
    person = get_user_person(connection)
    if person is None:
        return None
    with connection:
        connection.execute(
            "UPDATE people SET is_user = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (person.id,),
        )
    return Person(id=person.id, display_name=person.display_name, is_user=False)


def _person_from_row(row) -> Person:
    return Person(
        id=row["id"],
        display_name=row["display_name"],
        is_user=bool(row["is_user"]),
    )
