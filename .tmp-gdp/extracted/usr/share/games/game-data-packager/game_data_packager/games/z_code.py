#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# Copyright © 2016 Stephen Kitt
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import configparser
import logging
import os
import re
from shutil import which
from typing import (Any, TYPE_CHECKING)

from ..build import (PackagingTask)
from ..data import (Package)
from ..game import (GameData)
from ..util import (TemporaryUmask, mkdir_p)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class ZCodeGameData(GameData):
    def __init__(self, shortname: str, data: dict[str, Any]) -> None:
        super(ZCodeGameData, self).__init__(shortname, data)

        if self.engine is None:
            self.engine = {'deb': 'gargoyle-free | zcode-interpreter'}

        if self.genre is None:
            self.genre = 'Adventure'

    def construct_package(
        self,
        binary: str,
        data: dict[str, Any]
    ) -> ZCodePackage:
        return ZCodePackage(binary, data)

    def construct_task(self, **kwargs: Unpack[PackagingTaskArgs]) -> ZCodeTask:
        return ZCodeTask(self, **kwargs)


class ZCodePackage(Package):
    def __init__(self, binary: str, data: dict[str, Any]) -> None:
        super(ZCodePackage, self).__init__(binary, data)

        self.z_file = None
        for install in self.install:
            if re.match('^.z[12345678]$', os.path.splitext(install)[1]):
                assert self.z_file is None
                self.z_file = install

        assert self.z_file


class ZCodeTask(PackagingTask):
    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir
        assert isinstance(package, ZCodePackage)

        install_to = self.packaging.substitute(
            package.install_to, package.name,
        )

        with TemporaryUmask(0o022):
            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)
            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option     # type: ignore
            desktop['Desktop Entry'] = {}
            entry = desktop['Desktop Entry']
            entry['Type'] = 'Application'
            entry['Categories'] = 'Game;'
            assert type(self.game.genre) is str
            entry['GenericName'] = self.game.genre + ' Game'
            entry['Name'] = package.longname or self.game.longname
            entry['Terminal'] = 'false'
            engine = self.packaging.substitute(
                package.engine or self.game.engine, package.name,
            )
            if engine:
                engine = engine.split('|')[-1].strip()
                engine = self.packaging.tool_for_package(engine)
            else:
                # keep engines sorted by relevance
                for try_engine, terminal in (('gargoyle', False),
                                             ('gargoyle-free', False),
                                             ('frotz', True),
                                             ('nfrotz', True),
                                             ('fizmo', True),
                                             ('fizmo-cursenw', True),
                                             ('fizmo-console', True),
                                             ('zoom', False),
                                             ('zjip', True)):
                    if which(try_engine):
                        engine = try_engine
                        if terminal:
                            entry['Terminal'] = 'true'
                        break
                else:
                    engine = 'gargoyle'
            entry['TryExec'] = engine
            assert type(package.z_file) is str
            arg = os.path.join('/', install_to, package.z_file)
            entry['Exec'] = engine + ' ' + arg

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            if os.path.exists(
                os.path.join(pixdir, '%s.png' % self.game.shortname),
            ):
                entry['Icon'] = self.game.shortname
            else:
                entry['Icon'] = 'utilities-terminal'

            if package.aliases:
                entry['Keywords'] = ';'.join(package.aliases) + ';'

            with open(
                os.path.join(appdir, '%s.desktop' % package.name),
                'w', encoding='utf-8',
            ) as output:
                desktop.write(output, space_around_delimiters=False)

            per_package_state.lintian_overrides.add(
                'desktop-command-not-in-package {} '
                '[usr/share/applications/{}.desktop]'.format(
                    engine, package.name,
                )
            )

            bindir = self.packaging.substitute(
                self.packaging.BINDIR, package.name,
            )
            bindir = os.path.join(destdir, bindir.strip('/'))
            assert bindir.startswith(destdir + '/'), (bindir, destdir)
            assert '$' not in bindir
            mkdir_p(bindir)
            pgm = package.name[0:len(package.name)-len('-data')]
            path = os.path.join(bindir, pgm)
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n')
                f.write(
                    'command -v %s > /dev/null 2>&1 && exec %s $@ %s\n'
                    % (engine, engine, arg),
                )
                f.write(
                    'echo "You need to install some Z-Code interpreter '
                    'like Frotz or Gargoyle to play this game"\n',
                )
                os.chmod(path, 0o755)


GAME_DATA_SUBCLASS = ZCodeGameData
