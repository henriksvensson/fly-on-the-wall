from fly_on_the_wall.glossary import load_glossary_terms


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
