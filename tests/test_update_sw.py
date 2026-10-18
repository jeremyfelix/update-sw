"""Tests for bin/update-sw.  Nothing here runs a real subprocess."""

import importlib.machinery
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'bin' / 'update-sw'


def load_script():
    """Import the extension-less script as the module `update_sw`."""

    try:
        import tabulate  # noqa: F401
    except ImportError:
        stub = types.ModuleType('tabulate')
        stub.tabulate = lambda rows, **kwargs: '\n'.join(map(str, rows))
        sys.modules['tabulate'] = stub

    loader = importlib.machinery.SourceFileLoader('update_sw', str(SCRIPT))
    spec = importlib.util.spec_from_loader('update_sw', loader)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so plugins can `from update_sw import ...`.
    sys.modules['update_sw'] = module
    # Loading from bin/ would otherwise leave a __pycache__ there,
    # next to the script.
    sys.dont_write_bytecode = True
    loader.exec_module(module)
    return module


us = load_script()

BUILTINS = dict(us.REGISTRY)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Undo registrations and settings a test made."""

    us.SETTINGS.yes = False
    us.SETTINGS.dry_run = False
    yield
    us.REGISTRY.clear()
    us.REGISTRY.update(BUILTINS)
    sys.modules['update_sw'] = us


@pytest.fixture
def no_subprocess(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError(f'unexpected subprocess: {args}')

    monkeypatch.setattr(subprocess, 'run', fail)
    monkeypatch.setattr(subprocess, 'Popen', fail)


def set_platform(
    monkeypatch, *, darwin=False, distro='', wsl=False, available=()
):
    monkeypatch.setattr(us, 'is_darwin', lambda: darwin)
    monkeypatch.setattr(us, 'linux_distro', lambda: distro)
    monkeypatch.setattr(us, 'is_wsl', lambda: wsl)
    # Only the updaters whose tools may be missing; the rest are available
    # wherever they apply.
    for name in ('mas', 'pyenv', 'venv', 'rustup', 'cargo'):
        monkeypatch.setattr(
            us.REGISTRY[name],
            'available',
            classmethod(lambda cls, ok=name in available: ok),
        )


# Version parsing


@pytest.mark.parametrize(
    'name, impl, series, release',
    [
        ('3.13.2', 'cpython', (3, 13), (2,)),
        ('pypy3.10-7.3.15', 'pypy3', (3, 10), (7, 3, 15)),
        ('pypy2.7-7.3.1', 'pypy2', (2, 7), (7, 3, 1)),
        ('pypy3-7.3.1', 'pypy3', (3, 0), (7, 3, 1)),
    ],
)
def test_classify_version(name, impl, series, release):
    version = us.classify_version(name)
    assert (version.impl, version.series, version.release) == (
        impl,
        series,
        release,
    )


@pytest.mark.parametrize(
    'name',
    ['3.14.0rc1', '3.14.0t', '3.14-dev', 'system', 'anaconda3-2024.02', ''],
)
def test_classify_version_rejects(name):
    assert us.classify_version(name) is None


def test_latest_per_series_and_newest_series():
    names = ['3.12.1', '3.12.10', '3.12.9', '3.13.0', '3.14.0rc1', 'system']
    names += ['pypy3.10-7.3.15', 'pypy3.10-7.3.9']
    latest = us.latest_per_series(names)
    assert latest[('cpython', (3, 12))].name == '3.12.10'
    assert latest[('cpython', (3, 13))].name == '3.13.0'
    assert latest[('pypy3', (3, 10))].name == 'pypy3.10-7.3.15'
    assert len(latest) == 3

    newest = us.newest_series_per_impl(latest)
    assert newest['cpython'].name == '3.13.0'
    assert newest['pypy3'].name == 'pypy3.10-7.3.15'


# Registry


def test_registry_contents():
    assert set(BUILTINS) == {
        'windows-update',
        'windows-store',
        'macos',
        'brew',
        'mas',
        'apt',
        'emerge',
        'pip',
        'pyenv',
        'venv',
        'rustup',
        'cargo',
    }
    assert set(BUILTINS) == set(us.ORDER)
    assert len(us.ORDER) == len(set(us.ORDER))
    for name, cls in BUILTINS.items():
        assert cls.name == name


def test_abstract_helpers_are_not_registered():
    registered = set(us.REGISTRY.values())
    for cls in (
        us.Updater,
        us.CommandBasedUpdater,
        us.ExplorerUpdater,
        us.SinglePipUpdater,
    ):
        assert cls not in registered


def test_duplicate_name_is_an_error():
    with pytest.raises(ValueError, match='already registered'):

        class Again(us.Updater):
            name = 'brew'

    assert us.REGISTRY['brew'] is us.BrewUpdater


def test_nameless_updater_is_an_error():
    with pytest.raises(ValueError, match='no name'):

        class Nameless(us.Updater):
            pass


def test_subclass_registers_and_list_names_order():
    class Late(us.Updater):
        name = 'late'

    assert us.list_names() == [*us.ORDER, 'late']
    assert us.REGISTRY['late'] is Late


# Default sets


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (
            {'darwin': True, 'available': ['pyenv', 'venv']},
            ['macos', 'brew', 'pip', 'pyenv', 'venv'],
        ),
        (
            {'darwin': True, 'available': ['mas', 'rustup']},
            ['macos', 'brew', 'mas', 'pip', 'rustup'],
        ),
        (
            {
                'distro': 'ubuntu',
                'wsl': True,
                'available': ['pyenv', 'venv', 'rustup', 'cargo'],
            },
            [
                'windows-update',
                'windows-store',
                'apt',
                'pip',
                'pyenv',
                'venv',
                'rustup',
                'cargo',
            ],
        ),
        ({'distro': 'ubuntu'}, ['apt', 'pip']),
        ({'distro': 'raspbian'}, ['apt', 'pip']),
        ({'distro': 'debian'}, ['apt', 'pip']),
        ({'distro': 'gentoo'}, ['emerge', 'pip']),
        ({'distro': 'arch'}, ['pip']),
        ({}, ['pip']),
        # mas is installed but this is not a Mac.
        ({'distro': 'arch', 'available': ['mas']}, ['pip']),
    ],
)
def test_default_updaters(monkeypatch, kwargs, expected):
    set_platform(monkeypatch, **kwargs)
    assert us.default_updaters() == expected


# has_updates


def test_has_updates_brew():
    assert not us.BrewUpdater().has_updates('')
    assert us.BrewUpdater().has_updates('git\n')


def test_has_updates_apt():
    assert not us.AptUpdater().has_updates('Listing...\n')
    assert us.AptUpdater().has_updates('Listing...\nfoo/now 1.0 amd64\n')


def test_has_updates_macos():
    quiet = 'Software Update Tool\n\nFinding available software\n'
    assert not us.MacOsUpdater().has_updates(quiet)
    assert us.MacOsUpdater().has_updates(quiet + '* Label: macOS 15.1\n')


def test_has_updates_rustup():
    updater = us.RustupUpdater()
    assert updater.has_updates('stable - Update available : 1.80 -> 1.81')
    assert updater.has_updates('stable - update available : 1.80 -> 1.81')
    assert not updater.has_updates('stable - Up to date : 1.81')


def test_has_updates_cargo():
    header = 'Package  Installed  Latest  Needs update\n'
    updater = us.CargoUpdater()
    assert updater.has_updates(header + 'ripgrep  v14.0  v14.1  Yes\n')
    assert not updater.has_updates(header + 'ripgrep  v14.1  v14.1  No\n')
    assert not updater.has_updates('')


def test_has_updates_mas():
    assert not us.MasUpdater().has_updates('\n')
    assert us.MasUpdater().has_updates('497799835 Xcode (15.0)\n')


def test_command_attributes():
    assert us.BrewUpdater().outdated_cmd == (
        'brew',
        'outdated',
        '--fetch-HEAD',
    )
    assert us.BrewUpdater(fetch_head=False).upgrade_cmd == (
        'brew',
        'upgrade',
        '--yes',
    )
    assert us.CargoUpdater().upgrade_cmd[-1] == '--git'
    assert '--git' not in us.CargoUpdater(git=False).outdated_cmd
    assert us.RustupUpdater.outdated_ok_returncodes == (100,)
    assert us.RustupUpdater.update_is_fatal is False


# Steps and availability


def test_unimplemented_steps_print_nothing(capsys, no_subprocess):
    class Quiet(us.Updater):
        name = 'quiet'

    updater = Quiet()
    updater.update()
    updater.outdated()
    updater.upgrade()
    updater.cleanup()
    assert capsys.readouterr() == ('', '')


def test_command_updater_without_commands_prints_nothing(capsys):
    class Empty(us.CommandBasedUpdater):
        name = 'empty'

    Empty().run()
    assert capsys.readouterr() == ('', '')


def test_pyenv_outdated_runs_without_outdated_cmd(monkeypatch, capsys):
    monkeypatch.setattr(us.PyenvUpdater, 'has_update', False)
    monkeypatch.setattr(us.PyenvUpdater, '_outdated', lambda self: None)
    updater = us.PyenvUpdater()
    assert updater.outdated_cmd == ()
    assert not updater._has_step('update')
    updater.outdated()
    assert capsys.readouterr().out == 'Outdated (pyenv):\n\n'


def test_venv_and_explorer_only_have_their_steps():
    venv = us.VenvUpdater()
    assert [
        s for s in ('update', 'outdated', 'cleanup') if venv._has_step(s)
    ] == ['outdated']
    store = us.WindowsStoreUpdater()
    assert [
        s
        for s in ('update', 'outdated', 'upgrade', 'cleanup')
        if store._has_step(s)
    ] == ['update']


def test_unavailable_updater_prints_hint_by_name(monkeypatch, capsys):
    monkeypatch.setattr(
        us.MasUpdater, 'available', classmethod(lambda c: False)
    )
    us.MasUpdater().run()
    assert capsys.readouterr().out == (
        'Outdated (mas):\n'
        'mas is not installed.\nInstall it with: brew install mas\n\n'
    )


def test_cargo_hints(monkeypatch):
    monkeypatch.setattr(
        us.CargoUpdater, 'has_cargo', staticmethod(lambda: False)
    )
    monkeypatch.setattr(
        us.CargoUpdater, 'has_cargo_update', classmethod(lambda c: False)
    )
    assert 'cargo is not installed' in us.CargoUpdater.missing_hint()
    monkeypatch.setattr(
        us.CargoUpdater, 'has_cargo', staticmethod(lambda: True)
    )
    assert 'cargo install cargo-update' in us.CargoUpdater.missing_hint()
    monkeypatch.setattr(
        us.CargoUpdater, 'has_cargo_update', classmethod(lambda c: True)
    )
    assert us.CargoUpdater.missing_hint() is None
    assert us.CargoUpdater.available()


def test_generic_missing_hint(monkeypatch):
    monkeypatch.setattr(
        us.BrewUpdater, 'available', classmethod(lambda c: False)
    )
    assert us.BrewUpdater.missing_hint() == (
        'brew is not available on this system.'
    )
    monkeypatch.setattr(
        us.BrewUpdater, 'available', classmethod(lambda c: True)
    )
    assert us.BrewUpdater.missing_hint() is None


def test_rustup_availability(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] != 'rustup':
            raise FileNotFoundError(args[0])

    monkeypatch.setattr(subprocess, 'run', fake_run)
    us.command_succeeds.cache_clear()
    assert us.RustupUpdater.available()
    assert calls == [('rustup', '--version')]
    us.command_succeeds.cache_clear()


def test_requires_backs_availability(monkeypatch):
    class Needs(us.CommandBasedUpdater):
        name = 'needs'
        requires = 'needed-tool'

    monkeypatch.setattr(us.shutil, 'which', lambda cmd: None)
    assert not Needs.available()
    monkeypatch.setattr(us.shutil, 'which', lambda cmd: '/bin/' + cmd)
    assert Needs.available()


def test_single_pip_name_is_per_instance(monkeypatch):
    monkeypatch.setattr(us.shutil, 'which', lambda cmd: '/x/pip')
    assert us.SinglePipUpdater('pip', '3.13.1').name == 'pip (3.13.1)'
    assert us.SinglePipUpdater('pip').name == 'pip'
    assert 'pip (3.13.1)' not in us.REGISTRY


def test_pip_from_args_passes_options():
    args = types.SimpleNamespace(pip_bin='/opt/pip')
    updater = us.PipUpdater.from_args(args, {'skip': ['a']})
    assert (updater.pip_bin, updater.skip) == ('/opt/pip', ['a'])
    assert us.BrewUpdater.from_args(args, {}).__class__ is us.BrewUpdater


# confirm, --yes, --dry-run


def test_confirm_prompts(monkeypatch):
    answers = iter(['', 'y', 'n', 'N', 'whatever'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    assert [us.confirm('? ') for _ in range(5)] == [
        True,
        True,
        False,
        False,
        True,
    ]


def test_confirm_yes_does_not_prompt(monkeypatch, capsys):
    def no_input(prompt):
        raise AssertionError('prompted')

    monkeypatch.setattr('builtins.input', no_input)
    us.SETTINGS.yes = True
    assert us.confirm('Run upgrade (x)? [Y/n]: ')
    assert capsys.readouterr().out == 'Run upgrade (x)? [Y/n]: y\n'


def test_choose_target_under_yes(monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', lambda prompt: 1 / 0)
    us.SETTINGS.yes = True
    both = us.VenvMove('env', '3.12.1', '3.12.5', '3.13.0')
    assert us.VenvUpdater._choose_target(both) == '3.12.5'
    one = us.VenvMove('env', '3.12.1', None, '3.13.0')
    assert us.VenvUpdater._choose_target(one) == '3.13.0'
    assert 'Move env? [1/2/n]: 1' in capsys.readouterr().out


def test_choose_target_interactive(monkeypatch):
    both = us.VenvMove('env', '3.12.1', '3.12.5', '3.13.0')
    for reply, expected in [
        ('', '3.12.5'),
        ('2', '3.13.0'),
        ('n', None),
        ('9', None),
    ]:
        monkeypatch.setattr('builtins.input', lambda prompt, r=reply: r)
        assert us.VenvUpdater._choose_target(both) == expected


def test_dry_run_does_not_run_mutating_commands(no_subprocess, capsys):
    us.SETTINGS.dry_run = True
    us.SETTINGS.yes = True
    updater = us.BrewUpdater()
    updater.update()
    updater.upgrade()  # outdated_output is '' so nothing to upgrade
    updater.outdated_output = 'git\n'
    updater.upgrade()
    updater.cleanup()
    out = capsys.readouterr().out
    assert 'would run: brew update\n' in out
    assert 'would run: brew upgrade --yes --fetch-HEAD\n' in out
    assert 'would run: brew cleanup\n' in out


def test_dry_run_explorer_and_quoting(no_subprocess, capsys):
    us.SETTINGS.dry_run = True
    us.WindowsStoreUpdater().update()
    us.Updater._run(['echo', 'a b'])
    out = capsys.readouterr().out
    assert 'would run: explorer.exe ms-windows-store:\n' in out
    assert "would run: echo 'a b'\n" in out


def test_dry_run_still_runs_queries(monkeypatch, capsys):
    ran = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            ran.append(args)
            self.stdout = iter(['out\n'])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, 'Popen', FakePopen)
    us.SETTINGS.dry_run = True
    updater = us.BrewUpdater()
    updater.outdated()
    assert ran == [('brew', 'outdated', '--fetch-HEAD')]
    assert updater.outdated_output == 'out\n'


def test_dry_run_pyenv_upgrade(monkeypatch, no_subprocess, capsys):
    us.SETTINGS.dry_run = True
    us.SETTINGS.yes = True
    monkeypatch.setattr(us.PyenvUpdater, '_venvs_on', lambda self, base: ['e'])
    updater = us.PyenvUpdater()
    updater._upgrades = [us.PyenvUpgrade('3.12.1', '3.12.5')]
    updater.upgrade()
    assert (
        'would run: update-python --migrate-venvs 3.12.5 3.12.1'
        in capsys.readouterr().out
    )


# Failure handling


def test_rustup_update_failure_is_not_fatal(monkeypatch, capsys):
    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, 'run', fail)
    us.RustupUpdater().update()
    captured = capsys.readouterr()
    assert 'rustup: update failed' in captured.err
    assert '; continuing' in captured.err
    assert captured.out == 'Updating (rustup)...\n\n'


def test_fatal_update_failure_raises(monkeypatch):
    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        us.BrewUpdater().update()


def test_outdated_ok_returncodes(monkeypatch):
    class FakePopen:
        def __init__(self, args, **kwargs):
            self.stdout = iter(['Update available\n'])
            self.returncode = 100

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self):
            return self.returncode

    monkeypatch.setattr(subprocess, 'Popen', FakePopen)
    updater = us.RustupUpdater()
    updater.outdated()
    assert updater.has_updates(updater.outdated_output)
    with pytest.raises(subprocess.CalledProcessError):
        us.CommandBasedUpdater._run_with_output(('x',))


def test_run_each_aggregates(capsys):
    seen = []

    def fn(item):
        seen.append(item)
        if item in ('b', 'd'):
            raise subprocess.CalledProcessError(2, item)

    with pytest.raises(us.UpdaterError) as info:
        us.run_each('abcd', fn, str.upper)
    assert seen == ['a', 'b', 'c', 'd']
    assert info.value.failed == ['B', 'D']
    err = capsys.readouterr().err
    assert err.startswith('B: Command')
    assert '\nD: Command' in err


def test_run_each_success_and_uncaught():
    us.run_each([1, 2], lambda item: None, str)
    with pytest.raises(KeyError):
        us.run_each([1], lambda item: {}[item], str)
    with pytest.raises(us.UpdaterError):
        us.run_each(
            [1],
            lambda item: 1 / 0,
            str,
            catch=(ZeroDivisionError,),
        )


def test_pip_updater_continues_past_failures(monkeypatch, capsys):
    ran = []

    class Fake:
        def __init__(self, path, label, skip):
            self.path = path

        def run(self, skip_update):
            ran.append(self.path)
            if self.path == 'bad-oserror':
                raise OSError('nope')
            if self.path == 'bad-json':
                raise us.json.JSONDecodeError('bad', '', 0)

    monkeypatch.setattr(us, 'SinglePipUpdater', Fake)
    updater = us.PipUpdater()
    monkeypatch.setattr(
        updater,
        '_target_pips',
        lambda: [('bad-oserror', None), ('bad-json', 'v'), ('good', 'w')],
    )
    with pytest.raises(us.UpdaterError) as info:
        updater.run()
    assert ran == ['bad-oserror', 'bad-json', 'good']
    assert info.value.failed == ['bad-oserror', 'v']


def test_main_reports_failures_and_continues(monkeypatch, capsys):
    ran = []

    class Boom(us.Updater):
        name = 'boom'

        def run(self, skip_update=False):
            ran.append('boom')
            raise us.UpdaterError(['x'])

    class After(us.Updater):
        name = 'after'

        def run(self, skip_update=False):
            ran.append('after')

    assert us.main(['boom', 'after']) == 1
    assert ran == ['boom', 'after']
    assert 'Failed updaters: boom' in capsys.readouterr().err


def test_main_unknown_updater(capsys):
    assert us.main(['nope']) == 2
    assert 'Unknown updater(s): nope' in capsys.readouterr().err


# Config


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    (tmp_path / 'update-sw').mkdir()
    return tmp_path / 'update-sw'


def test_load_config_missing_is_empty(xdg):
    assert us.load_config() == {}


def test_load_config_explicit_missing_is_an_error(tmp_path):
    with pytest.raises(us.ConfigError):
        us.load_config(tmp_path / 'nope.toml')


def test_load_config_bad_toml(tmp_path):
    path = tmp_path / 'c.toml'
    path.write_text('exclude = [')
    with pytest.raises(us.ConfigError):
        us.load_config(path)


def test_example_config_is_a_no_op():
    example = SCRIPT.parent.parent / 'examples' / 'config.toml'
    assert us.load_config(example) == {}


def test_load_config_without_tomllib(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'c.toml'
    path.write_text('exclude = ["brew"]\n')
    monkeypatch.setattr(us, 'tomllib', None)
    assert us.load_config(path) == {}
    assert 'no tomllib' in capsys.readouterr().err


def test_config_default_exclude_extra(monkeypatch, capsys):
    set_platform(monkeypatch, distro='ubuntu', available=['mas'])
    assert us.default_updaters({'exclude': ['apt']}) == ['pip']
    # mas is known, so it lands at its ORDER position, not at the end.
    assert us.default_updaters({'extra': ['mas', 'pip']}) == [
        'mas',
        'apt',
        'pip',
    ]
    # An explicit default keeps its order and is not filtered by platform.
    assert us.default_updaters(
        {'default': ['pip', 'brew'], 'extra': ['apt'], 'exclude': ['brew']}
    ) == ['pip', 'apt']
    assert capsys.readouterr().err == ''


def test_config_unknown_names_warn(monkeypatch, capsys):
    set_platform(monkeypatch)
    names = us.default_updaters(
        {'exclude': ['nope'], 'extra': ['nada'], 'default': ['pip', 'zip']}
    )
    assert names == ['pip']
    err = capsys.readouterr().err
    for unknown in ('nope', 'nada', 'zip'):
        assert f"unknown updater '{unknown}'" in err


def test_config_bad_types_do_not_crash(monkeypatch, capsys):
    set_platform(monkeypatch)
    assert us.default_updaters({'exclude': 'pip', 'extra': [1]}) == ['pip']
    assert capsys.readouterr().err


def test_config_defined_updater(monkeypatch, capsys):
    set_platform(monkeypatch)
    config = {
        'updaters': {
            'flatpak': {
                'outdated': ['flatpak', 'remote-ls', '--updates'],
                'upgrade': ['flatpak', 'update'],
                'cleanup': ['flatpak', 'uninstall', '--unused'],
                'no_updates_output': 'Nothing to do',
                'requires': 'flatpak',
                'default': True,
            }
        }
    }
    us.register_config_updaters(config)
    cls = us.REGISTRY['flatpak']
    assert issubclass(cls, us.CommandBasedUpdater)
    assert cls.name == 'flatpak'
    assert cls.update_cmd == ()
    assert cls.upgrade_cmd == ('flatpak', 'update')
    assert cls.default is True

    updater = cls()
    assert updater._has_step('outdated')
    assert not updater._has_step('update')
    assert not updater.has_updates(' Nothing to do\n')
    assert updater.has_updates('org.gimp.GIMP\n')

    monkeypatch.setattr(us.shutil, 'which', lambda cmd: None)
    assert not cls.available()
    assert us.default_updaters(config) == ['pip']
    monkeypatch.setattr(us.shutil, 'which', lambda cmd: '/bin/flatpak')
    assert us.default_updaters(config) == ['pip', 'flatpak']
    assert capsys.readouterr().err == ''


def test_config_updater_default_has_updates_and_flags():
    cls = us.make_command_updater(
        'thing',
        {
            'outdated': ['thing', 'list'],
            'outdated_ok_returncodes': [3],
            'update_is_fatal': False,
        },
    )
    assert cls.default is False
    assert cls.outdated_ok_returncodes == (3,)
    assert cls.update_is_fatal is False
    assert not cls().has_updates('  \n')
    assert cls().has_updates('x')

    # With no outdated command, the upgrade is always offered.
    bare = us.make_command_updater('bare', {'upgrade': ['bare', 'up']})
    assert bare().has_updates('')


def test_config_updater_collision_and_errors(capsys):
    us.register_config_updaters(
        {
            'updaters': {
                'brew': {'upgrade': ['x']},
                'bad': {'upgrade': 'not-a-list'},
                'odd': 5,
            }
        }
    )
    err = capsys.readouterr().err
    assert "'brew' collides with a built-in" in err
    assert 'upgrade must be a list of strings' in err
    assert "'odd' should be a table" in err
    assert us.REGISTRY['brew'] is us.BrewUpdater
    assert 'bad' not in us.REGISTRY
    assert 'odd' not in us.REGISTRY


def test_per_updater_config_reaches_from_args():
    args = types.SimpleNamespace(pip_bin=None)
    brew = us.BrewUpdater.from_args(args, {'fetch_head': False})
    assert '--fetch-HEAD' not in brew.outdated_cmd
    cargo = us.CargoUpdater.from_args(args, {'git': False})
    assert '--git' not in cargo.upgrade_cmd


# Command line, config and plugins end to end


def test_main_list_with_config_and_plugin(xdg, capsys):
    (xdg / 'config.toml').write_text(
        '[updaters.flatpak]\nupgrade = ["flatpak", "update"]\n'
    )
    (xdg / 'updaters').mkdir()
    (xdg / 'updaters' / '10-good.py').write_text(
        'from update_sw import CommandBasedUpdater\n'
        'class SnapUpdater(CommandBasedUpdater):\n'
        '    name = "snap"\n'
        '    upgrade_cmd = ("snap", "refresh")\n'
    )
    (xdg / 'updaters' / '20-broken.py').write_text('raise RuntimeError("x")\n')
    (xdg / 'updaters' / '30-after.py').write_text(
        'from update_sw import Updater\n'
        'class LastUpdater(Updater):\n'
        '    name = "last"\n'
        '    default = False\n'
    )
    assert us.main(['--list']) == 0
    captured = capsys.readouterr()
    names = [
        line[2:]
        for line in captured.out.splitlines()
        if line[1:2] == ' ' and line[2:] in us.REGISTRY
    ]
    assert names == [*us.ORDER, 'flatpak', 'snap', 'last']
    assert '20-broken.py: failed to load plugin' in captured.err
    # Plugin classes are defaults, config-defined ones only when asked.
    marked = [
        line[2:]
        for line in captured.out.splitlines()
        if line.startswith('* ') and line[2:] in us.REGISTRY
    ]
    assert 'snap' in marked
    assert 'flatpak' not in marked
    assert 'last' not in marked


def test_main_exclude_and_unavailable_by_name(xdg, monkeypatch, capsys):
    (xdg / 'config.toml').write_text(
        '[updaters.flatpak]\n'
        'outdated = ["flatpak", "remote-ls"]\n'
        'upgrade = ["flatpak", "update"]\n'
        'requires = "definitely-not-installed-xyz"\n'
    )
    assert us.main(['-y', '-n', 'flatpak', 'brew', '-x', 'brew']) == 0
    out = capsys.readouterr().out
    assert out == (
        'Outdated (flatpak):\nflatpak is not available on this system.\n\n'
    )


def test_main_runs_config_updater_dry_run(xdg, monkeypatch, capsys):
    (xdg / 'config.toml').write_text(
        '[updaters.flatpak]\n'
        'update = ["flatpak", "update", "--appstream"]\n'
        'outdated = ["flatpak", "remote-ls"]\n'
        'upgrade = ["flatpak", "update"]\n'
        'cleanup = ["flatpak", "uninstall", "--unused"]\n'
    )
    monkeypatch.setattr(
        us.CommandBasedUpdater,
        '_run_with_output',
        staticmethod(lambda args, allowed_returncodes=(): 'org.gimp\n'),
    )
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: 1 / 0)
    assert us.main(['--yes', '--dry-run', 'flatpak']) == 0
    out = capsys.readouterr().out
    assert out == (
        'Updating (flatpak)...\n'
        'would run: flatpak update --appstream\n\n'
        'Outdated (flatpak):\n\n'
        'Run upgrade (flatpak)? [Y/n]: y\n'
        'would run: flatpak update\n\n'
        'Running cleanup (flatpak)...\n'
        'would run: flatpak uninstall --unused\n\n'
    )


def test_main_bad_config_is_exit_2(tmp_path, capsys):
    path = tmp_path / 'c.toml'
    path.write_text('this is not toml')
    assert us.main(['--config', str(path), '--list']) == 2
    assert 'Bad config' in capsys.readouterr().err


def test_main_config_exclude_applies_to_defaults(xdg, monkeypatch, capsys):
    set_platform(monkeypatch, distro='gentoo')
    (xdg / 'config.toml').write_text('exclude = ["emerge"]\n')
    ran = []
    monkeypatch.setattr(
        us.Updater,
        'run',
        lambda self, skip_update=False: ran.append(self.name),
    )
    assert us.main([]) == 0
    assert ran == ['pip']
    ran.clear()
    # -x applies on top of the config, and to explicit lists too.
    assert us.main(['-x', 'pip']) == 0
    assert ran == []
    assert us.main(['emerge', '-x', 'pip']) == 0
    assert ran == ['emerge']


def test_parser_flags():
    args = us.parse_args(['-y', '-n', '-x', 'a', '--exclude', 'b', '-c', 'f'])
    assert args.yes and args.dry_run
    assert args.exclude == ['a', 'b']
    assert args.config == Path('f')
