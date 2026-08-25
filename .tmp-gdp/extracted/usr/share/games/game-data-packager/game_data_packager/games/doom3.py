#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# Copyright © 2023 Sébastien Noel <sebastien@twolife.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import glob
import logging
import os
import subprocess
from typing import (TYPE_CHECKING)
from zipfile import ZipFile

from ..build import (FillResult, PackagingTask)
from ..game import (GameData)
from ..packaging import (get_native_packaging_system)
from ..util import (mkdir_p)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..data import (Package)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class Doom3GameData(GameData):
    def construct_task(self, **kwargs: Unpack[PackagingTaskArgs]) -> Doom3Task:
        return Doom3Task(self, **kwargs)


class Doom3Task(PackagingTask):
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
            'doom3-classic-data',
            'doom3-the-lost-mission-data',
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

        if package.name not in (
            'doom3-classic-data',
            'doom3-the-lost-mission-data',
        ):
            return

        libname = {
            'doom3-classic-data': 'cdoom',
            'doom3-the-lost-mission-data': 'd3le',
        }[package.name]

        # Build & install the mod lib
        packaging = get_native_packaging_system()
        libdir = packaging.get_libdir()
        install_all_dir = os.path.join(destdir, 'usr', 'share',
                                                'games', 'doom3', libname)
        install_arch_dir = os.path.join(destdir, 'usr', libdir, 'dhewm3')
        unpackdir = os.path.join(
            self.get_workdir(), 'tmp', package.name + '.build.d',
        )

        zips = list(glob.glob(os.path.join(install_all_dir, '*.zip')))
        assert len(zips) == 1, zips
        with ZipFile(zips[0]) as zObject:
            zObject.extractall(path=unpackdir)

        expect_dir_list = list(glob.glob(os.path.join(unpackdir, '*')))
        assert len(expect_dir_list) == 1, expect_dir_list
        expect_dir = os.path.basename(expect_dir_list[0])

        sourcedir = os.path.join(unpackdir, expect_dir)
        builddir = os.path.join(unpackdir, expect_dir, 'build')
        os.mkdir(builddir)
        mkdir_p(install_arch_dir)

        subprocess.check_call([
            'cmake', '-B', builddir, '-S', sourcedir,
        ])
        subprocess.check_call([
            'make', '-C', builddir, '-s', '-j5',
        ])
        subprocess.check_call([
            'install', '-s', '-m644',
            os.path.join(builddir, libname + '.so'),
            os.path.join(install_arch_dir, libname + '.so'),
        ])

        # Desktop file
        appdir = 'usr/share/applications'
        symlinkdir = '$assets/game-data-packager-runtime'
        symlinksrc = os.path.join(symlinkdir, 'dhewm3-%s.desktop' % libname)
        symlinkdest = os.path.join(appdir, 'dhewm3-%s.desktop' % libname)
        package.symlinks[symlinkdest] = symlinksrc


GAME_DATA_SUBCLASS = Doom3GameData
