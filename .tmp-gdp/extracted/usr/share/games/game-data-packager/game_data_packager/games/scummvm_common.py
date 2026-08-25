#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import configparser
import logging
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import (Iterable, Iterator)
from typing import (Any, TYPE_CHECKING)

from ..build import (PackagingTask)
from ..data import (Package, PackageRelation)
from ..game import (GameData)
from ..paths import DATADIR
from ..util import (mkdir_p)
from ..version import (GAME_PACKAGE_VERSION)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing import Unpack
    from ..packaging import (PerPackageState, PackagingTaskArgs)


def install_data(from_: str, to: str) -> None:
    subprocess.check_call(['cp', '--reflink=auto', from_, to])


class ScummvmPackage(Package):
    gameid: str | None


class ScummvmGameData(GameData):
    def __init__(self, shortname: str, data: dict[str, Any]) -> None:
        super(ScummvmGameData, self).__init__(shortname, data)

        self.wikibase = 'https://wiki.scummvm.org/index.php/'
        assert self.wiki

        if 'gameid' in self.data:
            self.gameid: str = self.data['gameid']
            assert self.gameid != shortname, \
                'extraneous gameid for ' + shortname
            self.aliases.add(self.gameid)
        else:
            self.gameid = shortname
        assert self.gameid

        if self.engine is None:
            self.engine = 'scummvm'
        if self.genre is None:
            self.genre = 'Adventure'

    def construct_package(self, binary: str, data: dict[str, Any]) -> Package:
        return ScummvmPackage(binary, data)

    def _populate_package(
        self,
        package: Package,
        d: dict[str, Any]
    ) -> None:
        super(ScummvmGameData, self)._populate_package(package, d)
        assert isinstance(package, ScummvmPackage), package
        package.gameid = d.get('gameid')

    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> ScummvmTask:
        return ScummvmTask(self, **kwargs)


class ScummvmTask(PackagingTask):
    def iter_extra_paths(
        self,
        packages: Iterable[Package]
    ) -> Iterator[str]:
        super(ScummvmTask, self).iter_extra_paths(packages)

        gameids = set()
        for p in packages:
            assert isinstance(self.game, ScummvmGameData), self.game
            assert isinstance(p, ScummvmPackage), p
            gameid = p.gameid or self.game.gameid
            if gameid == 'agi-fanmade':
                continue
            gameids.add(gameid.split('-')[0])
        if not gameids:
            return

        # http://wiki.scummvm.org/index.php/User_Manual/Configuring_ScummVM
        # https://github.com/scummvm/scummvm/pull/656
        config_home = os.environ.get(
            'XDG_CONFIG_HOME',
            os.path.expanduser('~/.config'),
        )
        for rcfile in (
            os.path.join(config_home, 'scummvm/scummvm.ini'),
            os.path.expanduser('~/.scummvmrc'),
            os.path.join(config_home, 'residualvm/residualvm.ini'),
            os.path.expanduser('~/.residualvmrc'),
        ):
            if os.path.isfile(rcfile):
                config = configparser.ConfigParser(strict=False)
                config.read(rcfile, encoding='utf-8')
                for section in config.sections():
                    for gameid in gameids:
                        if section.split('-')[0] == gameid:
                            if 'path' not in config[section]:
                                # invalid .scummvmrc
                                continue
                            path = config[section]['path']
                            if os.path.isdir(path):
                                yield path

    def download_icon(
        self,
        per_package_state: PerPackageState
    ) -> str | None:
        '''this is "Fair Use", the user already owns the game assets'''
        scummvm_toc = 'https://raw.githubusercontent.com/' + \
                      'scummvm/scummvm-icons/master/TOC.md'

        package = per_package_state.package
        dest_icon = os.path.join(self.get_workdir(), package.name + '.png')
        gameid = package.gameid or self.game.gameid
        dlfilename = None

        if not per_package_state.download:
            return None

        if ':' in gameid:
            splited = gameid.split(':')
            dlfilename = '%s-%s.png' % (splited[0], splited[1])
        else:
            try:
                response = urllib.request.urlopen(scummvm_toc)
            except urllib.error.HTTPError:
                logger.warning("Can't download %s", scummvm_toc)
                return None

            for line in response.read().decode('utf-8').split("\n"):
                if f"| {gameid} " in line:
                    splited = (line.split('|'))
                    splited = [s.strip() for s in splited]
                    if splited[1] == "✅":
                        dlfilename = '%s-%s.png' % (splited[2], splited[3])
                    else:
                        dlfilename = '%s.png' % splited[2]
                    break

        if dlfilename is None:
            logger.debug("Can't find an icon to download for '%s'", gameid)
            return None

        url = 'https://raw.githubusercontent.com/' + \
              'scummvm/scummvm-icons/master/icons/%s' % dlfilename
        try:
            logger.debug("Downloading icon %s", url)
            response = urllib.request.urlopen(url)
        except urllib.error.HTTPError:
            logger.warning("Can't download %s", url)
            return None

        with open(dest_icon, 'wb') as w:
            w.write(response.read())

        return dest_icon

    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir
        assert isinstance(self.game, ScummvmGameData), self.game
        assert isinstance(package, ScummvmPackage), package

        if package.type not in ('demo', 'full') and not package.gameid:
            return
        if package.data_type == 'binaries':
            return
        if package.name.endswith('-music'):
            return
        if package.name.endswith('-video'):
            return

        assert package.name.endswith('-data'), package.name

        package.relations['recommends'].append(
            PackageRelation(
                'game-data-packager-runtime (>= %s~)' % GAME_PACKAGE_VERSION
            )
        )

        icon = package.name[0:len(package.name)-len('-data')]
        pixdir = os.path.join(destdir, 'usr/share/pixmaps')
        for from_ in (self.locate_steam_icon(package),
                      os.path.join(pixdir, self.get_extra_icon_name(package)),
                      os.path.join(DATADIR, package.name + '.png'),
                      os.path.join(DATADIR, self.game.shortname + '.png'),
                      os.path.join('/usr/share/pixmaps', icon + '.png'),
                      os.path.join(
                          DATADIR,
                          self.game.shortname.strip('1234567890') + '.png'),
                      self.download_icon(per_package_state),
                      ):
            if from_ and os.path.exists(from_):
                mkdir_p(pixdir)
                install_data(from_, os.path.join(pixdir, '%s.png' % icon))
                break
        else:
            svgdir = '/usr/share/icons/hicolor/scalable/apps'
            symlinkdir = '$assets/game-data-packager-runtime'
            symlinksrc = os.path.join(symlinkdir, 'scummvm.svg')
            symlinkdest = os.path.join(svgdir, '%s.svg' % icon)
            package.symlinks[symlinkdest] = symlinksrc
            from_ = symlinkdest

        assert from_ is not None

        from_ = os.path.splitext(from_)[0] + '.svgz'
        if os.path.exists(from_):
            svgdir = os.path.join(
                destdir, 'usr/share/icons/hicolor/scalable/apps',
            )
            mkdir_p(svgdir)
            install_data(from_, os.path.join(svgdir, '%s.svgz' % icon))

        appdir = 'usr/share/applications'

        symlinkdir = '$assets/game-data-packager-runtime/scummvm'
        symlinksrc = os.path.join(symlinkdir, '%s.desktop' % icon)
        symlinkdest = os.path.join(appdir, '%s.desktop' % icon)
        package.symlinks[symlinkdest] = symlinksrc


GAME_DATA_SUBCLASS = ScummvmGameData
