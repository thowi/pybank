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

See `convert.py` and `fetch.py` for details on how to use it.

```bash
$ ./convert.py -i dkb-checking "$file" > "$outfile"
```

# Installation of web scrapers on macOS

Optional, if using the web scrapers:
```bash
$ brew install geckodriver chromedriver
```
