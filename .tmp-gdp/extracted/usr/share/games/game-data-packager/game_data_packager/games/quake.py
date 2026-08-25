#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from ..build import (PackagingTask)
from ..game import GameData
from ..util import TemporaryUmask, mkdir_p

if TYPE_CHECKING:
    import argparse
    from typing import Unpack
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class QuakeTask(PackagingTask):
    """With hindsight, it would have been better to make the TryExec
    in quake point to a symlink to the quake executable, or something;
    but with a name like hipnotic-tryexec.sh it would seem silly for it
    not to be a shell script.
    """

    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir

        for path in package.install:
            if path.startswith('hipnotic'):
                detector = 'hipnotic-tryexec.sh'
                break
            elif path.startswith('rogue'):
                detector = 'rogue-tryexec.sh'
                break
        else:
            return

        with TemporaryUmask(0o022):
            quakedir = os.path.join(destdir, 'usr/share/games/quake')
            mkdir_p(quakedir)
            path = os.path.join(quakedir, detector)
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexit 0\n')
            os.chmod(path, 0o755)


class QuakeGameData(GameData):
    def construct_task(self, **kwargs: Unpack[PackagingTaskArgs]) -> QuakeTask:
        return QuakeTask(self, **kwargs)

    def add_parser(
        self,
        parsers: argparse._SubParsersAction[Any],
        base_parser: argparse.ArgumentParser,
        **kwargs: Any,
    ) -> argparse.ArgumentParser:
        parser = super(QuakeGameData, self).add_parser(
            parsers, base_parser, conflict_handler='resolve',
        )
        parser.add_argument(
            '-m', dest='packages',
            action='append_const', const='quake-registered',
            help='Equivalent to --package=quake-registered',
        )
        parser.add_argument(
            '-s', dest='packages',
            action='append_const', const='quake-shareware',
            help='Equivalent to --package=quake-shareware',
        )
        parser.add_argument(
            '--mp1', '-mp1', dest='packages',
            action='append_const', const='quake-armagon',
            help='Equivalent to --package=quake-armagon',
        )
        parser.add_argument(
            '--mp2', '-mp2', dest='packages',
            action='append_const', const='quake-dissolution',
            help='Equivalent to --package=quake-dissolution',
        )
        parser.add_argument(
            '--music', dest='packages',
            action='append_const', const='quake-music',
            help='Equivalent to --package=quake-music',
        )
        parser.add_argument(
            '--mp1-music', dest='packages',
            action='append_const', const='quake-armagon-music',
            help='Equivalent to --package=quake-armagon-music',
        )
        parser.add_argument(
            '--mp2-music', dest='packages',
            action='append_const', const='quake-dissolution-music',
            help='Equivalent to --package=quake-dissolution-music',
        )
        return parser


GAME_DATA_SUBCLASS = QuakeGameData
