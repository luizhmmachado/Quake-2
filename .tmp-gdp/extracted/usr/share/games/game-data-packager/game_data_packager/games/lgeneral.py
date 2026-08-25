#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import (Iterable)
from typing import (Any, TYPE_CHECKING)

from ..build import (PackagingTask, NoPackagesPossible)
from ..game import (GameData)
from ..util import (mkdir_p)

if TYPE_CHECKING:
    import argparse
    from typing import (Unpack)
    from ..data import (Package)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class LGeneralGameData(GameData):
    def add_parser(
        self,
        parsers: argparse._SubParsersAction[Any],
        base_parser: argparse.ArgumentParser,
        **kwargs: Any,
    ) -> 'argparse.ArgumentParser':
        parser = super(LGeneralGameData, self).add_parser(parsers, base_parser)
        parser.add_argument(
            '-f', dest='download', action='store_false',
            help='Require pg-data.tar.gz on the command line',
        )
        parser.add_argument(
            '-w', dest='download', action='store_true',
            help='Download pg-data.tar.gz (done automatically if necessary)',
        )
        return parser

    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> LGeneralTask:
        return LGeneralTask(self, **kwargs)


class LGeneralTask(PackagingTask):
    def prepare_packages(
        self,
        packages: Iterable[Package] | None = None,
        build_demos: bool = False,
        download: bool = True,
        search: bool = True,
        log_immediately: bool = True,
        everything: bool = False,
        requested_packages: set[Package] = set()
    ) -> set[Package]:
        # don't bother even trying if it isn't going to work
        if shutil.which('lgc-pg') is None:
            logger.error('The "lgc-pg" tool is required for this package.')
            raise NoPackagesPossible()

        if 'DISPLAY' not in os.environ and 'WAYLAND_DISPLAY' not in os.environ:
            logger.error('The "lgc-pg" tool requires '
                         'to run in some graphical environment.')
            raise NoPackagesPossible()

        ready = super(LGeneralTask, self).prepare_packages(
            packages,
            build_demos=build_demos,
            download=download,
            search=search,
            log_immediately=log_immediately,
            everything=everything,
            requested_packages=requested_packages,
        )

        # would have raised an exception if not
        assert self.game.packages['lgeneral-data-nonfree'] in ready
        return ready

    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir
        assert package.name == 'lgeneral-data-nonfree'

        installdir = os.path.join(destdir, 'usr/share/games/lgeneral')
        unpackdir = os.path.join(self.get_workdir(), 'tmp', 'pg-data.tar.gz.d')

        for d in (
            'gfx/flags', 'gfx/terrain', 'gfx/units', 'maps/pg',
            'nations', 'scenarios/pg', 'sounds/pg', 'units',
        ):
            mkdir_p(os.path.join(installdir, d))

        shutil.unpack_archive(
                os.path.join(installdir, 'pg-data.tar.gz'),
                unpackdir,
                'gztar')

        subprocess.check_call([
            'lgc-pg', '-s', unpackdir + '/pg-data/',
            '-d', installdir + '/',
        ])


GAME_DATA_SUBCLASS = LGeneralGameData
