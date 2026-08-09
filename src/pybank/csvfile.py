import csv
from typing import TextIO


def read_csv_with_header(
    file: TextIO,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Processes a CSV file with a header and returns metadata and transactions.

    Some CSV files are a bit special and have a multi-line header, body, and
    perhaps a footer.

    Using this intermediate data structure allows for easier processing of some
    CSV files.

    :param file: The file object to read from.
    :return: The metadata as a dict and the rows as a list of dicts, each
    mapping from the columen name to the value (similar to `DictReader`).
    """
    # In case the file was read before, e.g. in the can_import pass.
    file.seek(0)
    reader = csv.reader(file, delimiter=';', quotechar='"')
    # Read metadata.
    metadata = {}
    col_names = None
    rows = []
    for row in reader:
        # Clean up the row.
        # Some CSVs wrap the values in a formula syntax.
        clean_row = []
        for col in row:
            if col.startswith('="') and col.endswith('"'):
                col = col[2:-1]  # strip ="
            clean_row.append(col)
        row = clean_row

        # Remove empty metadata columns.
        if not col_names:
            row = [col for col in row if col]

        # Skip empty/irrelevant rows.
        if len(row) < 2:
            continue

        # Read metadata.
        if len(row) == 2 and not col_names:
            metadata[row[0]] = row[1]
            continue

        # Read column names.
        if not col_names:
            col_names = row
            continue

        # Read transaction rows.
        rows.append(dict(zip(col_names, row)))

    return metadata, rows


def get_value(row: dict[str, str], keys: list[str]) -> str | None:
    """Returns the first value found in the row dict for the given keys.

    :param row: The row to search.
    :param keys: The keys to search for.
    :return: The first value found in the row for the given keys.
    """
    for key in keys:
        if key in row:
            return row[key]
    return None
