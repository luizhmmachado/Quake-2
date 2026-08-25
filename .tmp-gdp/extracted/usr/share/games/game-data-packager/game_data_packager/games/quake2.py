#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import glob
import logging
import os
import subprocess
import tarfile
from typing import (TYPE_CHECKING)
from zipfile import ZipFile

from ..build import (FillResult, PackagingTask)
from ..game import (GameData)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..data import (Package)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class Quake2GameData(GameData):
    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> Quake2Task:
        return Quake2Task(self, **kwargs)


class Quake2Task(PackagingTask):
    def fill_gaps(
        self,
        package: Package | None,
        download: bool = False,
        log: bool = True,
        recheck: bool = False,
        requested: bool = False,
    ) -> FillResult:
        assert package is not None
        if package.name in (
            'quake2-reckoning-data',
            'quake2-groundzero-data',
            'quake2-zaero-data',
        ) and (
            self.packaging.get_architecture()
            != self.builder_packaging.get_architecture()
        ):
            logger.warning('Cross-compiling %s not supported', package.name)
            return FillResult.IMPOSSIBLE

        return super().fill_gaps(
            package,
            download=download,
            log=log,
            recheck=recheck,
            requested=requested,
        )

    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir

        if package.name not in ('quake2-reckoning-data',
                                'quake2-groundzero-data',
                                'quake2-zaero-data',
                                ):
            return

        subdir = {
            'quake2-groundzero-data': 'rogue',
            'quake2-reckoning-data': 'xatrix',
            'quake2-zaero-data': 'zaero',
        }[package.name]

        source_is_github_commit_zip = {
            'quake2-groundzero-data': False,
            'quake2-reckoning-data': False,
            'quake2-zaero-data': True,
        }[package.name]

        installdir = os.path.join(destdir, 'usr', 'share', 'games', 'quake2')
        unpackdir = os.path.join(
            self.get_workdir(), 'tmp', package.name + '.build.d',
        )

        if source_is_github_commit_zip:
            zips = list(glob.glob(os.path.join(installdir, '*.zip')))
            assert len(zips) == 1, zips
            with ZipFile(zips[0]) as zObject:
                zObject.extractall(path=unpackdir)

            expect_dir_list = list(glob.glob(os.path.join(unpackdir, '*')))
            assert len(expect_dir_list) == 1, expect_dir_list
            expect_dir = os.path.basename(expect_dir_list[0])
        else:
            tars = list(glob.glob(os.path.join(installdir, '*.tar.xz')))
            assert len(tars) == 1, tars
            expect_dir = os.path.basename(tars[0])
            expect_dir = expect_dir[:len(expect_dir) - 7]

            with tarfile.open(tars[0], mode='r:xz') as tar:
                tar.extractall(unpackdir)

        subprocess.check_call([
            'make', '-C',
            os.path.join(unpackdir, expect_dir), '-s', '-j5',
        ])
        subprocess.check_call([
            'install', '-s', '-m644',
            os.path.join(unpackdir, expect_dir, 'release', 'game.so'),
            os.path.join(installdir, subdir, 'game.so'),
        ])


GAME_DATA_SUBCLASS = Quake2GameData
