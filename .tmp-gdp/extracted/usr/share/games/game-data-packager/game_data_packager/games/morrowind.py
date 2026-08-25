#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
# Copyright © 2016 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
from typing import (TYPE_CHECKING)

from ..build import (PackagingTask)
from ..game import (GameData)
from ..util import (check_call)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)


class MorrowindGameData(GameData):
    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> MorrowindTask:
        return MorrowindTask(self, **kwargs)


class MorrowindTask(PackagingTask):
    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir

        if package.expansion_for:
            return

        install_to = self.packaging.substitute(package.install_to,
                                               package.name)

        datadir = os.path.join(destdir, install_to.strip('/'))
        assert datadir.startswith(destdir + '/'), (datadir, destdir)

        subdir_expected_by_iniimporter = os.path.join(datadir, 'Data Files')
        os.symlink(datadir, subdir_expected_by_iniimporter)

        ini = os.path.join(datadir, 'Morrowind.ini')

        if os.path.exists(ini + '.gog'):
            # The GOG ini file already contains Tribunal and Bloodmoon
            initext = open(ini + '.gog', encoding='latin-1').read()
            open(ini, 'w', encoding='latin-1').write(initext)

        elif os.path.exists(ini + '.orig'):
            initext = open(ini + '.orig', encoding='latin-1').read()

            if package.name.startswith(     # either of:
                ('morrowind-tribunal', 'morrowind-complete'),
            ):
                initext = initext + '\r\nGameFile1=Tribunal.esm\r\n'

            if package.name.startswith('morrowind-bloodmoon'):
                initext = initext + '\r\nGameFile1=Bloodmoon.esm\r\n'

            if package.name.startswith('morrowind-complete'):
                initext = initext + '\r\nGameFile2=Bloodmoon.esm\r\n'

            open(ini, 'w', encoding='latin-1').write(initext)

        cfg = os.path.join(datadir, 'openmw.cfg')

        check_call(['openmw-iniimporter',
                    '--verbose',
                    '--game-files',
                    '--encoding', 'win1252',
                    '--ini', ini,
                    '--cfg', cfg])
        os.unlink(subdir_expected_by_iniimporter)

        with open(cfg, 'a', encoding='utf-8') as f:
            f.write('data=%s\n' % os.path.join('/', install_to))

        # then user needs to do this:
        #
        # $ mkdir -p ~/.config/openmw/
        # $ cp /usr/share/games/morrowind-fr/openmw.cfg ~/.config/openmw/


# See morrowind.txt for additional notes


GAME_DATA_SUBCLASS = MorrowindGameData
