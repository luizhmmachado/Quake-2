#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2023 Sébastien Noel <sebastien@twolife.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
from typing import (TYPE_CHECKING)
from zipfile import ZipFile

from ..build import (FillResult, PackagingTask)
from ..game import (GameData)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..data import (Package)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class LokiShimGameData(GameData):
    def construct_task(self, **kwargs: Unpack[PackagingTaskArgs]) -> LokiShim:
        return LokiShim(self, **kwargs)


class LokiShim(PackagingTask):
    def fill_gaps(
        self,
        package: Package | None,
        download: bool = False,
        log: bool = True,
        recheck: bool = False,
        requested: bool = False,
    ) -> FillResult:
        assert package is not None

        arch = self.builder_packaging.get_architecture()
        if arch not in ['amd64', 'i386']:
            logger.warning('Cross-compiling %s from %s not supported',
                           package.name, arch)
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
            'civctp-bin',
            'descent3-bin',
            'kohan-bin',
            'smac-bin',
        ):
            return

        # Extract, build & install the shim
        install_dir = os.path.join(destdir, 'usr', 'lib', self.game.shortname)
        unpackdir = os.path.join(
            self.get_workdir(), 'tmp', package.name + '.build.d',
        )

        zipname = os.path.join(destdir, 'usr', 'share',
                                        'games', self.game.shortname,
                                        'lokishim.zip')
        with ZipFile(zipname) as zObject:
            zObject.extractall(path=unpackdir)

        expect_dir_list = list(glob.glob(os.path.join(unpackdir, '*')))
        assert len(expect_dir_list) == 1, expect_dir_list
        expect_dir = os.path.basename(expect_dir_list[0])

        subprocess.check_call([
            'make', '-C',
            os.path.join(unpackdir, expect_dir), '-s',
        ])
        subprocess.check_call([
            'install', '-s', '-m644',
            os.path.join(unpackdir, expect_dir, 'lokishim.so'),
            os.path.join(install_dir, 'lokishim.so'),
        ])

        if package.name == 'civctp-bin':
            fixed_bin = os.path.join(unpackdir, 'civctp.dynamic_fixed')
            shutil.copyfile(
                os.path.join(install_dir, 'civctp.dynamic'),
                fixed_bin
            )

            # https://davidgow.net/hacks/civctp.html
            subprocess.check_call([
                'patchelf', '--replace-needed',
                'libSDL_mixer-1.0.so.0', 'libSDL_mixer-1.2.so.0', fixed_bin
            ])
            subprocess.check_call([
                'patchelf', '--replace-needed',
                'libSDL-1.1.so.0', 'libSDL-1.2.so.0', fixed_bin
            ])

            regex = 's/' \
                    r'\x{E8}\x{F5}\x{96}\x{B6}\x{FF}\x{89}\x{C0}\x{89}' \
                    r'\x{45}\x{FC}\x{8B}\x{43}\x{04}\x{3B}\x{45}\x{FC}' \
                    r'\x{75}\x{05}\x{FF}\x{43}\x{08}\x{EB}\x{14}/' \
                    r'\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}' \
                    r'\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}' \
                    r'\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}/'
            subprocess.check_call([
                'perl', '-pi', '-wE', regex, fixed_bin
            ])

            regex = 's/' \
                    r'\x{83}\x{7B}\x{08}\x{00}\x{7E}\x{05}\x{FF}\x{4B}' \
                    r'\x{08}\x{EB}\x{15}/' \
                    r'\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}\x{90}' \
                    r'\x{90}\x{90}\x{90}/'
            subprocess.check_call([
                'perl', '-pi', '-wE', regex, fixed_bin
            ])

            subprocess.check_call([
                'install', '-s', '-m755', fixed_bin,
                os.path.join(install_dir, 'civctp.dynamic_fixed'),
            ])


GAME_DATA_SUBCLASS = LokiShimGameData
