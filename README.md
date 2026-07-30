Python modules and scripts to download and convert bank statements.

# Set up the virtual environment and install requirements.

I'm using `uv` to create a virtual environment and install the dependencies:
```bash
$ uv venv
$ source .venv/bin/activate
$ uv sync
```

I recommend using (direnv)[https://direnv.net/] to automatically activate the
environment in your shell when entering the directory. Setup for this project:
```
$ echo 'export VIRTUAL_ENV=".venv"\nlayout python' > .envrc
$ direnv allow
```

# Run

Two entry points, `pybank-convert` and `pybank-fetch`. Run either with
`--help` for details.

```bash
$ uv run pybank-convert -i dkb-checking "$file" > "$outfile"
```

# Development

```bash
$ uv run pytest
$ uv run ruff check
$ uv run ruff format
```

# Web scrapers

The selenium scrapers under `src/pybank/download` are unmaintained. They are
kept for reference until replaced, see `docs/plans`. They need:
```bash
$ brew install geckodriver chromedriver
```
