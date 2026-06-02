from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from uuid import uuid4


@dataclass(frozen=True)
class Person:
    id: str
    display_name: str


def create_person(connection: Connection, display_name: str) -> Person:
    person = Person(id=str(uuid4()), display_name=display_name.strip())
    if not person.display_name:
        raise ValueError("Person display name cannot be empty.")

    with connection:
        connection.execute(
            "INSERT INTO people(id, display_name) VALUES (?, ?)",
            (person.id, person.display_name),
        )
    return person


def list_people(connection: Connection) -> list[Person]:
    rows = connection.execute(
        "SELECT id, display_name FROM people ORDER BY display_name"
    ).fetchall()
    return [Person(id=row["id"], display_name=row["display_name"]) for row in rows]


def get_person(connection: Connection, person_id_or_name: str) -> Person | None:
    row = connection.execute(
        """
        SELECT id, display_name FROM people
        WHERE id = ? OR lower(display_name) = lower(?)
        """,
        (person_id_or_name, person_id_or_name),
    ).fetchone()
    if row is None:
        return None
    return Person(id=row["id"], display_name=row["display_name"])
