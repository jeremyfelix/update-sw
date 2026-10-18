# update-sw

Updates software on various platforms with one command. Each kind of software
(brew, pip, cargo, and so on) is handled by an updater with up to four
optional steps: update, outdated, upgrade and cleanup. `update-sw --list`
shows the known updater names.

## Scripts

- `bin/update-sw`: runs the updaters, by default the set that applies to the
  current platform. Pass updater names to run only those.
- `bin/update-python`: installs a pyenv Python version and migrates an
  existing version's packages onto it.
- `bin/update-venv`: moves pyenv virtualenvs onto a newer base Python,
  preserving their packages. `update-python --migrate-venvs` and update-sw's
  `venv` updater both use it.

Run any of them with `--help` for the options.

## Install

Put `bin/` on your `PATH`, and install the dependencies:

    pip install tabulate
    pip install distro    # optional, Linux only

See `requirements.txt`. Reading the TOML config needs Python 3.11 or later
(`tomllib`); on older versions the config file is ignored.

## Configuration

An optional TOML file at `${XDG_CONFIG_HOME:-~/.config}/update-sw/config.toml`
(or the file given with `--config`) adjusts what runs. Every key is optional;
see `examples/config.toml` for commentary.

Every `*.py` file in `${XDG_CONFIG_HOME:-~/.config}/update-sw/updaters/` is
loaded as a plugin that can define more updaters. The module docstring of
`bin/update-sw` describes the plugin interface with an example.

## Tests

    pip install pytest tabulate
    pytest

## License

BSD 2-Clause; see `LICENSE`.
