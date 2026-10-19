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

Clone the repository, put `bin/` on your `PATH`, and install the
dependencies:

    git clone https://github.com/jeremyfelix/update-sw

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

## Updating update-sw itself

When update-sw runs from a git clone that has an upstream branch, the `self`
updater runs first. It fetches, shows the new commits and (after the usual
prompt) fast-forwards the clone, which also updates `update-python` and
`update-venv`. update-sw then restarts on the new code with the same
arguments, so the rest of the run uses it.

`self` fetches from the clone's own remote, so clone over https to avoid SSH
key prompts (for example from a hardware-backed or Secretive key) on every
run. If the clone already uses SSH and you push from it, fetch over https and
keep pushing over SSH with:

    git remote set-url origin https://github.com/jeremyfelix/update-sw
    git remote set-url --push origin git@github.com:jeremyfelix/update-sw.git

The merge is `--ff-only`, so local changes or commits make it fail rather than
being overwritten. Turn it off with `-x self` or `exclude = ['self']` in the
config. Only git installs are supported, and a checkout with a detached HEAD,
such as a git submodule, has no upstream; use a standalone clone and symlink
its `bin/` scripts onto your `PATH` instead.

## Versions

Each script prints its version with `--version` (or `-V`), for example
`update-sw v1.0.0-3-g22b5d76`. It comes from `git describe --tags --always
--dirty` in the clone the script lives in (following symlinks), or is
`unknown` outside a git clone. There is nothing to bump by hand. To release,
tag the commit and push the tag:

    git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push --tags

When `self` finds updates it shows the change as `v1.0.0 -> v1.1.0`, so
releases are worth tagging.

## Tests

    pip install pytest tabulate
    pytest

## License

BSD 2-Clause; see `LICENSE`.
