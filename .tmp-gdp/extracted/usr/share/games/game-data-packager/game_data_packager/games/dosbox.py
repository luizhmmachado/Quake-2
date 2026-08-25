#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

# this is just a proof-of-concept,
# please don't start packaging 10.000 DOS games

from __future__ import annotations

import configparser
import logging
import os
from typing import (Any, TYPE_CHECKING)

from ..build import (PackagingTask)
from ..data import (Package)
from ..game import (GameData)
from ..util import (mkdir_p)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class DosboxGameData(GameData):
    """Special subclass of GameData for DOS games.

    These games will need the "dosgame" runtime
    provided by src:game-data-packager.
    """

    def __init__(self, shortname: str, data: dict[str, Any]) -> None:
        super(DosboxGameData, self).__init__(shortname, data)
        self.binary_executables = 'all'

    def construct_package(
        self,
        binary: str,
        data: dict[str, Any]
    ) -> DosboxPackage:
        return DosboxPackage(binary, data)

    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> DosboxTask:
        return DosboxTask(self, **kwargs)


class DosboxPackage(Package):
    def __init__(self, binary: str, data: dict[str, Any]) -> None:
        super(DosboxPackage, self).__init__(binary, data)

        assert 'install_to' not in data
        assert 'depends' not in data

        self.install_to = '$assets/dosbox/' + self.name[:len(self.name)-5]
        self.depends = 'dosgame'
        self.main_exe: str
        if 'main_exe' in data:
            self.main_exe = data['main_exe']
            return

        for wanted in self.install:
            filename, ext = os.path.splitext(wanted)
            if (
                filename not in ('config', 'install', 'setup')
                and ext in ('.com', '.exe')
            ):
                self.main_exe = filename
                return


class DosboxTask(PackagingTask):
    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir
        assert isinstance(package, DosboxPackage)

        pgm = package.name[:len(package.name)-5]
        bindir = self.packaging.substitute(self.packaging.BINDIR, package.name)
        mkdir_p(os.path.join(destdir, bindir.strip('/')))
        os.symlink('dosgame', os.path.join(destdir, bindir.strip('/'), pgm))

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option     # type: ignore
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.game.longname
        entry['Icon'] = 'dosbox'
        if self.game.genre is None:
            entry['GenericName'] = 'game'
        else:
            entry['GenericName'] = self.game.genre + ' game'
        entry['Exec'] = pgm
        entry['Terminal'] = 'false'
        entry['Type'] = 'Application'
        entry['Categories'] = 'Game;'

        with open(
            os.path.join(appdir, '%s.desktop' % package.name),
            'w', encoding='utf-8',
        ) as output:
            desktop.write(output, space_around_delimiters=False)

        # minimal information needed by the runtime
        dosgame = configparser.RawConfigParser()
        dosgame.optionxform = lambda option: option     # type: ignore
        dosgame['Dos Game'] = {}
        entry = dosgame['Dos Game']
        entry['Dir'] = package.main_exe
        entry['Exe'] = package.main_exe

        install_to = self.packaging.substitute(
            package.install_to, package.name,
        )
        with open(
            os.path.join(destdir, install_to.strip('/'), 'dosgame.inf'),
            'w', encoding='utf-8',
        ) as output:
            dosgame.write(output, space_around_delimiters=False)


GAME_DATA_SUBCLASS = DosboxGameData
