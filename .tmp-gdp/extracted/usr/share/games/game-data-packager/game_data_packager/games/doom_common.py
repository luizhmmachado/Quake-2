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
from typing import (Any, TYPE_CHECKING)

from ..build import (PackagingTask)
from ..data import (Package)
from ..game import (GameData)
from ..paths import (DATADIR, ICONS)
from ..util import (copy_with_substitutions, mkdir_p)

if TYPE_CHECKING:
    from typing import (Unpack)
    from ..packaging import (PerPackageState, PackagingTaskArgs)

logger = logging.getLogger(__name__)

try:
    from omg import WAD
    from PIL import Image
    have_omg = True
except ImportError:
    have_omg = False


def install_data(from_: str, to: str) -> None:
    subprocess.check_call(['cp', '--reflink=auto', from_, to])


class DoomGameData(GameData):
    """Special subclass of GameData for games descended from Doom.
    These games install their own icon and .desktop file, and share a
    considerable amount of other data.

    Please do not follow this example for newly-supported games other than
    the Doom family (Doom, Heretic, Hexen, Strife, Hacx, Chex Quest).

    For new games it is probably better to use game-data-packager to ship only
    the non-distributable files, and ship DFSG files (such as icons
    and .desktop files) somewhere else.

    One way is to have the engine package contain the wrapper scripts,
    .desktop files etc. (e.g. src:openjk, src:iortcw). This is the simplest
    thing if the engine is unlikely to be used for other games and alternative
    engine versions are unlikely to be packaged.

    Another approach is to have a package for the engine (like src:ioquake3)
    and a package for the user-visible game (like src:quake, containing
    wrapper scripts, .desktop files etc.). This is more flexible if the engine
    can be used for other user-visible games (e.g. OpenArena, Nexuiz Classic)
    or there could reasonably be multiple packaged engines (e.g. Quakespasm,
    Darkplaces).
    """

    def __init__(self, shortname: str, data: dict[str, Any]) -> None:
        super(DoomGameData, self).__init__(shortname, data)

        self.wikibase = 'http://doomwiki.org/wiki/'
        assert self.wiki

        if self.engine is None:
            self.engine = {
                    'deb': "chocolate-doom | doom-engine",
                    'generic': 'chocolate-doom'
                    }

        if self.genre is None:
            self.genre = 'First-person shooter'

        for package in self.packages.values():
            assert isinstance(package, DoomPackage)
            for main_wad in package.main_wads.values():
                if 'args' not in main_wad and package.expansion_for:
                    assert self.packages[package.expansion_for].only_file

    def construct_package(
        self,
        binary: str,
        data: dict[str, Any]
    ) -> DoomPackage:
        return DoomPackage(binary, data)

    def construct_task(self, **kwargs: Unpack[PackagingTaskArgs]) -> DoomTask:
        return DoomTask(self, **kwargs)


class DoomPackage(Package):
    main_wads: dict[str, dict[str, str]]

    def __init__(self, binary: str, data: dict[str, Any]) -> None:
        super(DoomPackage, self).__init__(binary, data)

        assert 'install_to' not in data, self.name
        assert 'data_type' not in data, self.name

        self.install_to = '$assets/doom'

        if self.expansion_for or self.expansion_for_ext:
            self.data_type = 'PWAD'
        else:
            self.data_type = 'IWAD'

        if 'main_wads' in data:
            self.main_wads = data['main_wads']
        else:
            assert self.only_file
            self.main_wads = {self.only_file: {}}

        assert isinstance(self.main_wads, dict)
        for main_wad in self.main_wads.values():
            assert isinstance(main_wad, dict)
            if 'args' in main_wad:
                # assert that it has one string placeholder
                main_wad['args'] % 'deadbeef'


class DoomTask(PackagingTask):
    def extract_icon(
        self,
        destdir: str,
        package: Package,
        main_wad: str,
        desktop_file: str,
    ) -> None:
        if not have_omg:
            logger.warning(
                'Unable to load omgifol and PIL modules. '
                'No icons will get extracted from WAD files.'
            )
            return

        if package.name in ('hexen-wad', 'hexen-demo-wad'):
            title_lumps = ('M_HTIC',)
            add_transparency = True
        else:
            title_lumps = ('DMENUPIC', 'TITLEPIC', 'INTERPIC')
            add_transparency = False

        try:
            wad_file = os.path.join(
                destdir,
                self.packaging.substitute(
                    package.install_to, package.name,
                ).strip('/'),
                main_wad,
            )
            wad_obj = WAD(wad_file)
            lump_obj = None
            for lump in title_lumps:
                try:
                    lump_obj = wad_obj.graphics[lump]
                    break
                except KeyError:
                    continue
            else:
                return

            if add_transparency:
                top_left = lump_obj.to_pixels()[0]

                if top_left is not None:
                    lump_obj.palette.tran_index = top_left

            im = lump_obj.to_Image(mode='RGBA')
            w, h = im.size
            # maintain the proper 1.2:1 pixel aspect ratio
            im = im.resize((5 * w, 6 * h), Image.NEAREST)
            canvas = (256, 256)
            im.thumbnail(canvas, Image.Resampling.LANCZOS)
            w, h = im.size
            icon = Image.new('RGBA', canvas)
            offset = (canvas[0] - w) // 2, (canvas[1] - h) // 2
            icon.paste(im, offset)
            pixdir = os.path.join(
                destdir, 'usr', 'share', 'icons', 'hicolor',
                'x'.join([str(x) for x in canvas]), 'apps',
            )
            mkdir_p(pixdir)
            icon.save(os.path.join(pixdir, '%s.png' % desktop_file))
        except Exception as e:
            logger.error('Failed to generate icon: %s' % e)

    def fill_extra_files(
        self,
        per_package_state: PerPackageState
    ) -> None:
        super().fill_extra_files(per_package_state)
        package = per_package_state.package
        destdir = per_package_state.destdir
        assert isinstance(package, DoomPackage)

        for main_wad, quirks in package.main_wads.items():
            engine = self.packaging.substitute(
                package.engine or self.game.engine, package.name,
            )
            assert type(engine) is str
            engine = engine.split('|')[-1].strip()
            engine = engine.split(maxsplit=1)[0]
            program = self.packaging.tool_for_package(engine)

            wad_base = os.path.splitext(main_wad)[0]

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            mkdir_p(pixdir)
            # FIXME: would be nice if non-Doom games could replace this
            # Cacodemon with something appropriate
            desktop_file = package.name
            if len(package.main_wads) > 1:
                desktop_file += '-' + wad_base

            for basename in (
                    quirks.get('icon', wad_base),
                    package.name,
                    self.game.shortname,
                    'doom-common',
            ):
                from_ = os.path.join(ICONS, basename + '.png')
                if os.path.exists(from_):
                    install_data(
                        from_,
                        os.path.join(pixdir, '%s.png' % desktop_file),
                    )
                    break
            else:
                raise AssertionError(
                    'doom-common.png should have existed in {}'.format(ICONS)
                )

            for ext in ('.svgz', '.svg'):
                from_ = os.path.splitext(from_)[0] + ext
                if os.path.exists(from_):
                    svgdir = os.path.join(
                        destdir,
                        'usr/share/icons/hicolor/scalable/apps',
                    )
                    mkdir_p(svgdir)
                    install_data(
                        from_,
                        os.path.join(svgdir, desktop_file + ext),
                    )

            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)

            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option     # type: ignore
            desktop['Desktop Entry'] = {}
            entry = desktop['Desktop Entry']
            entry['Name'] = package.longname or self.game.longname
            if 'name' in quirks:
                entry['Name'] = quirks['name']
            assert type(self.game.genre) is str
            entry['GenericName'] = self.game.genre + ' game'
            entry['TryExec'] = program

            install_to = self.packaging.substitute(
                package.install_to, package.name,
            )

            self.extract_icon(destdir, package, main_wad, desktop_file)

            if 'args' in quirks:
                pwad = os.path.join('/', install_to, main_wad)
                args = quirks['args'] % pwad
            elif package.expansion_for:
                iwad = self.game.packages[package.expansion_for].only_file
                assert iwad is not None, "Couldn't find %s's IWAD" % main_wad
                iwad = os.path.join('/', install_to, iwad)
                pwad = os.path.join('/', install_to, main_wad)
                args = ' '.join(('-iwad', iwad, '-file', pwad))
            else:
                iwad = os.path.join('/', install_to, main_wad)
                args = ' '.join(('-iwad', iwad))
            entry['Exec'] = program + ' ' + args
            entry['Icon'] = desktop_file
            entry['Terminal'] = 'false'
            entry['Type'] = 'Application'
            entry['Categories'] = 'Game;'
            entry['Keywords'] = wad_base + ';'

            with open(
                os.path.join(appdir, '%s.desktop' % desktop_file),
                'w', encoding='utf-8',
            ) as output:
                desktop.write(output, space_around_delimiters=False)

            per_package_state.lintian_overrides.add(
                'desktop-command-not-in-package {} '
                '[usr/share/applications/{}.desktop]'.format(
                    program, desktop_file,
                )
            )

        preinst_in = os.path.join(DATADIR, 'doom-common.preinst.in')
        if self.packaging.derives_from('deb') and os.path.isfile(preinst_in):
            for main_wad in package.main_wads:
                if main_wad in (
                    'doom.wad', 'doom2.wad', 'plutonia.wad', 'tnt.wad',
                ):
                    debdir = os.path.join(destdir, 'DEBIAN')
                    mkdir_p(debdir)
                    copy_with_substitutions(
                        open(preinst_in, encoding='utf-8'),
                        open(
                            os.path.join(debdir, 'preinst'), 'w',
                            encoding='utf-8',
                        ),
                        IWAD=main_wad)
                    os.chmod(os.path.join(debdir, 'preinst'), 0o755)


GAME_DATA_SUBCLASS = DoomGameData
