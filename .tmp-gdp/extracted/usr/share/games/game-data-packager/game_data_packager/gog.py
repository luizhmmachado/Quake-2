#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import json
import logging
import os
import subprocess
from shutil import which
from typing import (TYPE_CHECKING)

from .packaging import (get_native_packaging_system)
from .util import (
    ascii_safe,
    check_output,
    lang_score,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import argparse
    from .game import GameData


class Gog:
    available: list[str] | None = None

    def owned_games(self) -> list[str]:
        if self.available is not None:
            return self.available

        self.available = []
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not which('lgogdownloader'):
            pass
        elif os.path.isfile(cache):
            data = json.load(open(cache, encoding='utf-8'))
            for key in data['games']:
                self.available.append(key['gamename'])
        else:
            try:
                list = check_output(
                    ['lgogdownloader', '--list'],
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                assert type(list) is str
                self.available = list.splitlines()
            except subprocess.CalledProcessError:
                pass

        return self.available

    def is_native(self, wanted: str) -> bool:
        cache = os.path.expanduser(
            '~/.cache/lgogdownloader/gamedetails.json'
        )
        if not os.path.isfile(cache):
            return False

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            if game['gamename'] != wanted:
                continue
            for installer in game['installers']:
                if installer['platform'] == 4:
                    return True
        return False

    def get_id_from_archive(self, archive: str) -> str | None:
        cache = os.path.expanduser(
            '~/.cache/lgogdownloader/gamedetails.json'
        )
        if not os.path.isfile(cache):
            return None

        archive = os.path.basename(archive)

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            for installer in game['installers']:
                if installer['path'].endswith(archive):
                    gamename = game['gamename']
                    assert type(gamename) is str
                    return gamename
        return None

    def verify_checksum(self, archive: str, size: int, md5: str) -> bool:
        basename = os.path.basename(archive)
        extension = os.path.splitext(basename)[1]
        if not (
            basename.startswith('gog_') and extension == '.sh'
            or basename.startswith('setup_') and extension == '.exe'
        ):
            return False

        xml_root = os.path.expanduser('~/.cache/lgogdownloader/xml/')
        if not os.path.isdir(xml_root):
            return False

        for dirpath, dirnames, filenames in os.walk(xml_root):
            for fn in filenames:
                if fn != basename + '.xml':
                    continue
                xml_file = os.path.join(dirpath, fn)
                xml = open(xml_file, 'r', encoding='utf-8').readline()
                xml = xml.strip('<>\n')
                for tag in xml.split(' '):
                    if '=' not in tag:
                        continue
                    k, v = tag.split('=', 2)
                    v = v.strip('"')
                    if k == 'md5' and v != md5:
                        return False
                    elif k == 'total_size' and int(v) != size:
                        return False
                else:
                    return True
        return False


GOG = Gog()


def run_gog_meta_mode(
    parsed: argparse.Namespace,
    games: dict[str, GameData]
) -> None:
    packaging = get_native_packaging_system()
    if not which('lgogdownloader') or not which('innoextract'):
        logger.error("You need to install lgogdownloader & innoextract first")
        logger.error(
            "$ su -c '%s lgogdownloader innoextract'"
            % ' '.join(packaging.INSTALL_CMD)
        )
        return

    owned = GOG.owned_games()
    if not owned:
        logger.error(
            "Couldn't locate any game, running 'lgogdownloader --login'"
        )
        subprocess.call(['lgogdownloader', '--login'])
        logger.info("... and now 'lgogdownloader --update-cache'")
        subprocess.call(['lgogdownloader', '--update-cache'])
        GOG.available = None
        owned = GOG.owned_games()
    logger.info("Found %d game(s) !" % len(owned))

    found_games = set()
    found_packages = []
    for game, data in games.items():
        for package in data.packages.values():
            gog_id = data.gog_download_name(package)
            if gog_id is None or gog_id not in owned:
                continue
            if lang_score(package.lang) == 0:
                continue

            can_do_better = False

            for v in package.better_versions:
                if data.gog_download_name(data.packages[v]):
                    can_do_better = True
                    break

            if can_do_better:
                continue

            installed = packaging.is_installed(package.name)
            if parsed.new and installed:
                continue
            found_games.add(game)
            longname = package.longname or data.longname
            assert type(longname) is str
            found_packages.append({
                'game': game,
                'type': 1 if package.type == 'full' else 2,
                'package': package.name,
                'installed': installed,
                'longname': longname,
                'id': gog_id,
               })
    if not found_games:
        logger.error('No supported GOG.com games found')
        return

    print('[x] = package is already installed')
    found_packages = sorted(
        found_packages,
        key=lambda k: (k['game'], k['type'], k['longname']),
    )
    for g in sorted(found_games):
        ids = set()
        for p in found_packages:
            if p['game'] == g:
                ids.add('"%s"' % p['id'])
        print('%s - provided by %s' % (g, ','.join(ids)))
        for p in found_packages:
            if p['game'] == g:
                longname2 = p['longname']
                assert type(longname2) is str
                print(
                    '[%s] %-42s    %s' % (
                        'x' if p['installed'] else ' ',
                        p['package'],
                        ascii_safe(longname2),
                    )
                )
        print()
