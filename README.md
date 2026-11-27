Python modules and scripts to download bank statements and import them into
Beancount.

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

Two entry points, `pybank-import` and `pybank-fetch`. Run either with
`--help` for details.

```bash
$ uv run pybank-import --config "$config" extract "$statements" > "$outfile"
```

# Development

```bash
$ uv run pytest
$ uv run ruff check
$ uv run ruff format
```

The review page of `pybank-import review-ui` is a React app in `web/`. Its
build goes into `src/pybank/web/static/`:
```bash
$ cd web && npm install && npm run build
```

# Web scrapers

The selenium scrapers under `src/pybank/download` are unmaintained. They are
kept for reference until replaced, see `docs/plans`. They need:
```bash
$ brew install geckodriver chromedriver
```
