#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
import time
import zipfile
from types import TracebackType
from typing import (Any, NoReturn)

from .config import (read_config)
from .data import (ProgressCallback)
from .game import (load_games)
from .packaging import (get_packaging_system)
from .paths import (DATADIR)
from .util import (human_size)
from .version import (FORMAT, DISTRO, GAME_PACKAGE_VERSION)

logger = logging.getLogger(__name__)


class TerminalProgress(ProgressCallback):
    def __init__(
        self,
        interval: float = 0.2,
        info: str | None = None,
    ) -> None:
        """Constructor.

        Progress will update at most once per @interval seconds, unless we
        are at a "checkpoint".
        """
        self.pad = ' '
        self.interval = interval
        self.ts = time.time()
        self.info = info

    def __call__(
        self,
        done: int | None = None,
        total: int | None = None,
        checkpoint: bool = False
    ) -> None:
        ts = time.time()

        if done is None or (ts < self.ts + self.interval and not checkpoint):
            return

        if self.info is not None:
            print(self.info, file=sys.stderr)
            self.info = None

        if done is None or total == 0:
            s = ''
        elif total is None or total == 0:
            s = human_size(done)
        else:
            s = '%.0f%% %s/%s' % (
                100 * done / total,
                human_size(done),
                human_size(total),
            )

        self.ts = ts

        if len(self.pad) <= len(s):
            self.pad = ' ' * len(s)

        print(' %s \r %s\r' % (self.pad, s), end='', file=sys.stderr)

    def __enter__(self) -> TerminalProgress:
        return self

    def __exit__(
        self,
        _et: type[BaseException] | None = None,
        _ev: BaseException | None = None,
        _tb: TracebackType | None = None
    ) -> None:
        self()


def run_command_line() -> None:
    logger.debug('Arguments: %r', sys.argv)

    # Don't set any defaults on these base parsers, because that interferes
    # with the ability to recognise the same argument either before or
    # after the game name. Set them on the Namespace instead.
    base_parser = argparse.ArgumentParser(
        prog='game-data-packager',
        description='Package game files.',
        add_help=False,
        argument_default=argparse.SUPPRESS,
    )

    class VersionAction(argparse.Action):
        def __call__(
            self,
            parser: Any,
            namespace: argparse.Namespace,
            values: Any,
            option_string: str | None = None
        ) -> None:
            print(GAME_PACKAGE_VERSION)
            exit(0)

    base_parser.add_argument(
        '--version', action=VersionAction, nargs=0,
        help='display version and exit',
    )

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument(
        '--verbose', action='store_true',
        help='show output from external tools',
    )
    group.add_argument(
        '--no-verbose', action='store_false',
        dest='verbose',
        help='hide output from external tools (default)',
    )

    class DebugAction(argparse.Action):
        def __call__(
            self,
            parser: Any,
            namespace: argparse.Namespace,
            values: Any,
            option_string: str | None = None
        ) -> None:
            logging.getLogger().setLevel(logging.DEBUG)

    base_parser.add_argument(
        '--debug', action=DebugAction, nargs=0,
        help='show debug messages',
    )

    game_parser = argparse.ArgumentParser(
        prog='game-data-packager',
        description='Package game files.',
        add_help=False,
        argument_default=argparse.SUPPRESS,
        parents=(base_parser,),
    )

    game_parser.add_argument(
        '--everything', action='store_true',
        help='Download all possible expansions',
    )
    game_parser.add_argument(
        '--package', '-p', action='append',
        dest='packages', metavar='PACKAGE',
        help='Produce this data package (may be repeated)',
    )

    game_parser.add_argument(
        '--target-format',
        choices='arch deb rpm'.split(),
        help='Produce packages for this packaging system',
    )
    game_parser.add_argument(
        '--target-distro',
        help='Produce packages suitable for this distro',
    )
    game_parser.add_argument(
        '--target-architecture',
        help=(
            'Produce packages suitable for this architecture (named '
            'according to either the --target-distro or dpkg conventions)'
        ),
    )

    game_parser.add_argument(
        '--install-method', metavar='METHOD',
        dest='install_method',
        help=(
            'Use METHOD (apt, dpkg, gdebi, gdebi-gtk, gdebi-kde) '
            'to install packages'
        ),
    )

    game_parser.add_argument(
        '--gain-root-command', metavar='METHOD',
        dest='gain_root_command',
        help='Use METHOD (su, sudo, pkexec) to gain root if needed',
    )

    # This is about ability to audit, not freeness. We don't have an
    # option to restrict g-d-p to dealing with Free Software, because
    # that would rule out the vast majority of its packages: if a game's
    # data is Free Software, we could put it in main or contrib and not need
    # g-d-p at all.
    game_parser.add_argument(
        '--binary-executables', action='store_true',
        help=(
            'allow installation of executable code that was not built '
            'from public source code'
        ),
    )
    game_parser.add_argument(
        '--demo', action='store_true',
        help=(
            'Build demo/shareware packages even if files for a full version '
            'are available'
        ),
    )

    # Misc options
    group = game_parser.add_mutually_exclusive_group()
    group.add_argument(
        '-i', '--install', action='store_true',
        help='install the generated package',
    )
    group.add_argument(
        '--force-install', action='store_true',
        help='install the generated package without prompting',
    )
    group.add_argument(
        '-n', '--no-install', action='store_false',
        dest='install',
        help='do not install the generated package (requires -d, default)',
    )

    game_parser.add_argument(
        '-d', '--destination', metavar='OUTDIR',
        help='write the generated .%s(s) to OUTDIR' % FORMAT,
    )

    group = game_parser.add_mutually_exclusive_group()
    group.add_argument(
        '-z', '--compress', action='store_true',
        help='compress generated .%s (default if -d is used)' % FORMAT,
    )
    group.add_argument(
        '--no-compress', action='store_false', dest='compress',
        help='do not compress generated .%s (default without -d)' % FORMAT,
    )

    group = game_parser.add_mutually_exclusive_group()
    group.add_argument(
        '--download', action='store_true',
        help='automatically download necessary files if possible (default)',
    )
    group.add_argument(
        '--no-download', action='store_false', dest='download',
        help='do not download anything',
    )
    game_parser.add_argument(
        '--save-downloads', metavar='DIR',
        help='save downloaded files to DIR, and look for files there',
    )

    group = game_parser.add_mutually_exclusive_group()
    group.add_argument(
        '--search', action='store_true',
        help=(
            'look for installed files in Steam and other likely places '
            '(default)'
        ),
    )
    group.add_argument(
        '--no-search', action='store_false', dest='search',
        help='only look in paths provided on the command line',
    )

    class DumbParser(argparse.ArgumentParser):
        def error(self, message: Any) -> NoReturn:  # type: ignore[empty-body]
            pass

    dumb_parser = DumbParser(parents=(game_parser,), add_help=False)
    dumb_parser.add_argument('game', type=str, nargs='?')
    dumb_parser.add_argument('paths', type=str, nargs='*')
    dumb_parser.add_argument('-h', '--help', action='store_true', dest='h')
    try:
        g = dumb_parser.parse_args().game
    except TypeError:
        g = None
    zip = os.path.join(DATADIR, 'vfs.zip')
    if g is None:
        games = load_games()
    elif '-h' in sys.argv or '--help' in sys.argv:
        games = load_games()
    elif os.path.isfile(os.path.join(DATADIR, '%s.json' % g)):
        games = load_games(game=g)
    elif not os.path.isfile(zip):
        games = load_games()
    else:
        with zipfile.ZipFile(zip, 'r') as zf:
            if '%s.json' % g in zf.namelist():
                games = load_games(game=g)
            else:
                games = load_games()

    parser = argparse.ArgumentParser(
        prog='game-data-packager',
        description='Package game files.', parents=(game_parser,),
        epilog=(
            'Run "game-data-packager GAME --help" to see game-specific '
            'arguments.'
        ),
    )

    game_parsers = parser.add_subparsers(
        dest='shortname',
        title='supported games',
        metavar='GAME',
    )

    for g in sorted(games.keys()):
        games[g].add_parser(game_parsers, game_parser)

    # GOG meta-mode
    gog_parser = game_parsers.add_parser(
        'gog',
        help='Package all your GOG.com games at once',
        description='Automatically package all your GOG.com games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=(game_parser,),
    )
    group = gog_parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', default=False,
                       help='show all GOG.com games')
    group.add_argument('--new', action='store_true', default=False,
                       help='show all new GOG.com games')

    # Steam meta-mode
    steam_parser = game_parsers.add_parser(
        'steam',
        help='Package all Steam games at once',
        description='Automatically package all your Steam games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=(game_parser,),
    )
    group = steam_parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', default=False,
                       help='package all Steam games')
    group.add_argument('--new', action='store_true', default=False,
                       help='package all new Steam games')

    mt_parser = game_parsers.add_parser(
        'make-template',
        help='Capture details of a new game or update an existing one',
        description=textwrap.dedent('''\
        This command collects details of game files in a directory or archive,
        so that they can be used for a newly supported game or added to an
        existing game. Please send its output to the Debian bug tracking system
        as a bug with 'wishlist' severity.\
        '''),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=(base_parser,),
    )
    mt_parser.add_argument('args', nargs='*', metavar='DEB|DIRECTORY|FILE')
    mt_parser.add_argument(
        '--strip-path', action='append', dest='strip_paths', default=[],
        help='Strip a prefix from all filenames (may be repeated)')
    mt_parser.add_argument(
        '--base', default=None, help='Base the template on an existing game')
    mt_parser.add_argument(
        '--template', action='append', dest='templates', default=[],
        help='Load pre-generated templates')
    mt_parser.add_argument(
        '-l', '--lower', action='store_true', dest='lower',
        help='make all files lowercase')
    mt_parser.add_argument(
        '-e', '--execute', action='store_true', dest='execute',
        help='run this game through strace and see which files from '
             '/usr/share/games or /usr/local/games are needed')
    mt_parser.add_argument(
        '-f', '--flacsums', action='store_true', dest='flacsums',
        help='compute "flacsums" from .wav files')

    config = read_config()
    parsed = argparse.Namespace(
            binary_executables=False,
            compress=None,
            demo=False,
            destination=None,
            download=True,
            everything=False,
            force_install=False,
            verbose=False,
            install=False,
            install_method='',
            gain_root_command='',
            packages=[],
            save_downloads=None,
            search=True,
            shortname=None,
            target_architecture=None,
            target_format=FORMAT,
            target_distro=DISTRO,
    )
    if config['install']:
        logger.debug('obeying INSTALL=yes in configuration')
        parsed.install = True
    if config['preserve']:
        logger.debug('obeying PRESERVE=yes in configuration')
        parsed.destination = '.'
    if config['verbose']:
        logger.debug('obeying VERBOSE=yes in configuration')
        parsed.verbose = True
    if config['install_method']:
        logger.debug(
            'obeying INSTALL_METHOD=%r in configuration',
            config['install_method'],
        )
        parsed.install_method = config['install_method']
    if config['gain_root_command']:
        logger.debug(
            'obeying GAIN_ROOT_COMMAND=%r in configuration',
            config['gain_root_command'],
        )
        parsed.gain_root_command = config['gain_root_command']

    parser.parse_args(namespace=parsed)
    parsed.install = parsed.install or parsed.force_install
    logger.debug('parsed command-line arguments into: %r', parsed)

    if (parsed.destination is None and not parsed.install and
            parsed.shortname != 'make-template'):
        logger.error('At least one of --install or --destination is required')
        sys.exit(2)

    if parsed.shortname is None:
        parser.print_help()
        sys.exit(0)

    for arg, path in (('--save-downloads', parsed.save_downloads),
                      ('--destination', parsed.destination)):
        if path is None:
            continue
        elif not os.path.isdir(path):
            logger.error('argument "%s" to %s does not exist', path, arg)
            sys.exit(2)
        elif not os.access(path, os.W_OK | os.X_OK):
            logger.error('argument "%s" to %s is not writable', path, arg)
            sys.exit(2)
        elif path == '.':
            try:
                os.getcwd()
            except FileNotFoundError:
                logger.error('argument "%s" to %s has been deleted', path, arg)
                sys.exit(2)

    if parsed.shortname == 'steam':
        from .steam import (run_steam_meta_mode)
        run_steam_meta_mode(parsed, games)
        return
    elif parsed.shortname == 'gog':
        from .gog import (run_gog_meta_mode)
        run_gog_meta_mode(parsed, games)
        return
    elif parsed.shortname == 'make-template':
        import game_data_packager.make_template
        game_data_packager.make_template.main(parsed, games)
        return
    elif parsed.shortname in games:
        game = games[parsed.shortname]
    else:
        parsed.package = parsed.shortname
        for game in games.values():
            if parsed.shortname in game.packages:
                break
            if parsed.shortname in game.aliases:
                break
        else:
            raise AssertionError('could not find %s' % parsed.shortname)

    with game.construct_task(
        packaging=get_packaging_system(
            parsed.target_format,
            parsed.target_distro,
            parsed.target_architecture,
        ),
    ) as task:
        if sys.stderr.isatty():
            task.progress_factory = TerminalProgress

        task.run_command_line(parsed)


if __name__ == '__main__':
    run_command_line()
