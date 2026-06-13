from fly_on_the_wall.db import database
from fly_on_the_wall.glossary import (
    create_glossary_term,
    glossary_prompt_lines,
    list_glossary_terms,
    load_glossary_terms,
    remove_glossary_term,
    transcription_keyterms,
    update_glossary_term,
)
from fly_on_the_wall.people import create_person


def test_load_glossary_terms_reads_list(tmp_path) -> None:
    path = tmp_path / "glossary.yaml"
    path.write_text("- Person A\n- Example Company\n")

    assert load_glossary_terms(path) == ["Example Company", "Person A"]


def test_load_glossary_terms_reads_mapping_values(tmp_path) -> None:
    path = tmp_path / "glossary.yaml"
    path.write_text("people:\n  - Person A\ncompanies:\n  - Example Company\n")

    assert load_glossary_terms(path) == ["Example Company", "Person A"]


def test_load_glossary_terms_handles_missing_file(tmp_path) -> None:
    assert load_glossary_terms(tmp_path / "missing.yaml") == []


def test_glossary_term_crud(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        created = create_glossary_term(connection, "  Hejare  ", " my company ")
        updated = update_glossary_term(connection, created.id, description="Company name")
        terms = list_glossary_terms(connection)
        removed = remove_glossary_term(connection, "Hejare")

    assert created.term == "Hejare"
    assert created.description == "my company"
    assert updated.description == "Company name"
    assert [term.term for term in terms] == ["Hejare"]
    assert removed is True


def test_glossary_prompt_lines_merge_people_and_legacy_yaml(tmp_path) -> None:
    legacy = tmp_path / "glossary.yaml"
    legacy.write_text("- Hejare\n- Person A\n")

    with database(tmp_path / "fly.db") as connection:
        create_glossary_term(connection, "Hejare", "Company name")
        create_glossary_term(connection, "Datadrivna", "The phrase data driven in Swedish")
        create_person(connection, "Person A")
        lines = glossary_prompt_lines(connection, legacy)

    assert lines == [
        "Datadrivna: The phrase data driven in Swedish",
        "Hejare: Company name",
        "Person A",
    ]


def test_transcription_keyterms_filter_provider_limits(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        create_glossary_term(connection, "Hejare", "Company name")
        create_glossary_term(connection, "Too many words in this one phrase")
        create_glossary_term(connection, "Bad [term]")
        create_person(connection, "Person A")
        keyterms = transcription_keyterms(connection)

    assert keyterms == ["Hejare", "Person A"]
