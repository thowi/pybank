from pybank import text


def test_normalize_text_pins_the_import_id_contract():
    """A change here changes every import-id, see docs/importing.md."""
    raw = "  GROCER   LTD  \nCard  payment \n"
    assert text.normalize_text(raw) == "Grocer Ltd\nCard payment"


def test_normalize_text_keeps_none():
    assert text.normalize_text(None) is None
