#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
from collections.abc import (Sequence)
from typing import (TYPE_CHECKING)

from ..build import (PackagingTask)
from ..game import (GameData)
from ..util import (TemporaryUmask, mkdir_p)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..data import (Package)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class UnrealTask(PackagingTask):
    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir

        if package.name == 'unreal-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'skaarj_logo.jpg')
        elif package.name == 'ut99-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'ut99.png')
        elif package.name == 'ut2004-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'ut2004.png')

        if package.name in ('unreal-gold', 'unreal-classic', 'ut99-data'):
            with TemporaryUmask(0o022):
                self.__add_manifest(package, destdir)

    def __add_manifest(self, package: Package, destdir: str) -> None:
        # A real Manifest.ini is much larger than this, but this is
        # enough to identify the version.

        install_to = self.packaging.substitute(
            package.install_to,
            package.name,
        )
        system = os.path.join(destdir, install_to.strip('/'), 'System')
        assert system.startswith(destdir + '/'), (system, destdir)
        mkdir_p(system)

        with open(os.path.join(system, 'Manifest.ini'), 'w') as writer:
            if package.name == 'unreal-gold':
                groups: Sequence[tuple[str, str, str]] = (
                    ('UnrealGold', package.name, package.version),
                    ('Unreal Gold', package.name, package.version),
                )
                sample_file = 'System\\UnrealLinux.ini'
            elif package.name == 'unreal-classic':
                groups = (('Unreal', package.name, package.version),)
                sample_file = 'System\\UnrealLinux.ini'
            elif package.name == 'ut99-data':
                # The unofficial patches after 436 do not update the manifest
                groups = (('UnrealTournament', 'ut99', '436'),)
                sample_file = 'System\\UnrealTournament.ini'
            else:
                raise AssertionError(
                    'Method should not be called for this package',
                )

            lines = ['[Setup]', 'MasterProduct=' + groups[0][0]]

            for g in groups:
                lines.append('Group=' + g[0])

            for g in groups:
                lines.append('')
                lines.append('[' + g[0] + ']')
                lines.append('Caption=' + g[1])
                lines.append('Version=' + g[2])
                lines.append('File=' + sample_file)

            lines += [
                '',
                '[RefCounts]',
                'File:%s=%d' % (sample_file, len(groups)),
                '',
            ]

            for line in lines:
                writer.write(line + '\r\n')

    def __convert_logo(
        self,
        destdir: str,
        package: Package,
        logo_name: str,
    ) -> None:
        source_logo = os.path.join(
            destdir,
            self.packaging.substitute(
                package.install_to, package.name,
            ).strip('/'),
            logo_name,
        )
        assert source_logo.startswith(destdir + '/'), (source_logo, destdir)

        try:
            import gi
            gi.require_version('GdkPixbuf', '2.0')
            from gi.repository import GdkPixbuf
        except Exception:
            logger.warning(
                'Unable to load GdkPixbuf bindings. %s icon '
                'will not be resized or converted',
                self.game.longname,
            )
            return

        mkdir_p(os.path.join(destdir, 'usr', 'share', 'icons',
                'hicolor', '48x48', 'apps'))
        mkdir_p(os.path.join(destdir, 'usr', 'share', 'icons',
                'hicolor', '256x256', 'apps'))

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(source_logo)
        assert pixbuf
        pixbuf.savev(
            os.path.join(
                destdir, 'usr', 'share', 'icons',
                'hicolor', '256x256', 'apps', self.game.shortname + '.png'
            ),
            'png', [], [],
        )

        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(source_logo, 48, 48)
        assert pixbuf
        pixbuf.savev(
            os.path.join(
                destdir, 'usr', 'share', 'icons',
                'hicolor', '48x48', 'apps', self.game.shortname + '.png',
            ),
            'png', [], [],
        )


class UnrealGameData(GameData):
    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> UnrealTask:
        return UnrealTask(self, **kwargs)


GAME_DATA_SUBCLASS = UnrealGameData
