"""All values here are invented."""

import codecs
import io

from pybank import csvfile

STATEMENT = """\
Konto:;="CH00 0000 0000 0000 0000 0"
Währung:;="CHF"

Datum;Avisierungstext;Gutschrift in CHF;Lastschrift in CHF
05.01.2026;GROCER LTD;;42.50

Disclaimer:
Some trailing prose that is not a transaction.
"""


def _write(tmp_path, content, encoding):
    path = tmp_path / "statement.csv"
    path.write_bytes(content.encode(encoding))
    return str(path)


def test_read_text_handles_every_encoding_in_the_archive(tmp_path):
    """Two banks, four export generations, three encodings between them."""
    text = "Konto:;Zürich"
    assert csvfile.read_text(_write(tmp_path, text, "utf-8")) == text
    assert csvfile.read_text(_write(tmp_path, text, "utf-8-sig")) == text
    assert csvfile.read_text(_write(tmp_path, text, "cp1252")) == text


def test_read_text_strips_the_bom(tmp_path):
    """A leading BOM would end up inside the first metadata key."""
    decoded = csvfile.read_text(_write(tmp_path, "Konto:;x", "utf-8-sig"))
    assert not decoded.startswith(codecs.BOM_UTF8.decode("utf-8"))
    assert decoded.startswith("Konto:")


def test_read_csv_with_header_splits_metadata_from_rows():
    metadata, rows = csvfile.read_csv_with_header(io.StringIO(STATEMENT))

    assert metadata == {"Konto:": "CH00 0000 0000 0000 0000 0", "Währung:": "CHF"}
    assert rows == [
        {
            "Datum": "05.01.2026",
            "Avisierungstext": "GROCER LTD",
            "Gutschrift in CHF": "",
            "Lastschrift in CHF": "42.50",
        }
    ]


def test_read_csv_with_header_strips_the_formula_wrapper():
    """Some exports wrap values as `="..."` to stop Excel reformatting them."""
    metadata, _rows = csvfile.read_csv_with_header(io.StringIO(STATEMENT))
    assert not metadata["Konto:"].startswith('="')


def test_read_csv_with_header_rereads_from_the_start():
    """`identify()` reads the file before `extract()` does."""
    handle = io.StringIO(STATEMENT)
    first = csvfile.read_csv_with_header(handle)
    assert csvfile.read_csv_with_header(handle) == first


def test_get_value_takes_the_first_column_that_exists():
    row = {"Buchungsdatum": "2026-01-05"}
    assert csvfile.get_value(row, ["Datum", "Buchungsdatum"]) == "2026-01-05"
    assert csvfile.get_value(row, ["Valuta"]) is None
