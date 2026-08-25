#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import glob
import logging
import os
import tempfile
import xml.etree.ElementTree
import urllib.request
from collections.abc import (Iterator)
from typing import (TYPE_CHECKING)

from .build import (
    BinaryExecutablesNotAllowed,
    DownloadsFailed,
    NoPackagesPossible,
)
from .packaging import (get_native_packaging_system)
from .util import (
    AGENT,
    ascii_safe,
    lang_score,
    rm_rf,
)

if TYPE_CHECKING:
    import argparse
    from .game import GameData

logger = logging.getLogger(__name__)


def parse_acf(path: str) -> Iterator[dict[str, str]]:
    for manifest in glob.glob(path + '/*.acf'):
        with open(manifest) as data:
            # the .acf files are not really JSON files
            level = 0
            acf_struct = {}
            for line in data.readlines():
                if line.strip() == '{':
                    level += 1
                elif line.strip() == '}':
                    level -= 1
                elif level != 1:
                    continue
                elif '"\t\t"' in line:
                    key, value = line.split('\t\t')
                    key = key.strip().strip('"')
                    value = value.strip().strip('"')
                    if key in ('appid', 'name', 'installdir'):
                        acf_struct[key] = value
            if 'name' not in acf_struct:
                acf_struct['name'] = acf_struct['installdir']
            yield acf_struct


STEAM_GAMES: list[tuple[int, str]] | None = None


def owned_steam_games(
    steam_id: str | None = None,
) -> list[tuple[int, str]]:
    global STEAM_GAMES
    if steam_id is None:
        steam_id = get_steam_id()
    if STEAM_GAMES is not None:
        return STEAM_GAMES
    STEAM_GAMES = []
    if steam_id is None:
        return []
    url = "http://steamcommunity.com/profiles/" + steam_id + "/games?xml=1"
    try:
        html = urllib.request.urlopen(
            urllib.request.Request(url, headers={'User-Agent': AGENT}),
        )
        tree = xml.etree.ElementTree.ElementTree()
        tree.parse(html)
        games_xml = tree.iter('game')
        for game in games_xml:
            el = game.find('appID')
            assert el
            assert el.text
            appid = int(el.text)
            el = game.find('name')
            assert el
            assert el.text
            name = el.text
            # print(appid, name)
            STEAM_GAMES.append((appid, name))
    except urllib.error.URLError:
        # e="[Errno 111] Connection refused" but e.errno=None ?
        pass

    return STEAM_GAMES


def get_steam_id() -> str | None:
    path = os.path.expanduser('~/.steam/config/loginusers.vdf')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', ) as data:
        for line in data.readlines():
            line = line.strip('\t\n "')
            if line not in ('users', '{'):
                return line
    return None


def get_steam_account() -> str | None:
    path = os.path.expanduser('~/.steam/config/loginusers.vdf')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', ) as data:
        for line in data.readlines():
            if 'AccountName' in line:
                return line.split('"')[-2]
    return None


class FoundPackage:
    def __init__(
        self,
        game: str,
        game_type: int,
        package: str,
        installed: bool,
        longname: str,
        paths: list[str],
    ) -> None:
        self.game = game
        self.game_type = type
        self.package = package
        self.installed = installed
        self.longname = longname
        self.paths = paths


def run_steam_meta_mode(
    args: argparse.Namespace,
    games: dict[str, GameData]
) -> None:
    logger.info(
        'Visit our community page: '
        'https://steamcommunity.com/groups/debian_gdp#curation',
    )
    owned = set()
    if args.download:
        steam_id = get_steam_id()
        if steam_id is None:
            logger.error(
                "Couldn't read SteamID from ~/.steam/config/loginusers.vdf"
            )
        else:
            logger.info('Getting list of owned games from '
                        'http://steamcommunity.com/profiles/' + steam_id)
            owned = set(g[0] for g in owned_steam_games(steam_id))

    logging.info('Searching for locally installed Steam games...')
    found_games = []
    found_packages = []
    tasks = {}
    packaging = get_native_packaging_system()

    for game, gamedata in games.items():
        for package in gamedata.packages.values():
            id = package.steam.get('id') or gamedata.steam.get('id')
            if not id:
                continue

            if package.type == 'demo':
                continue
            # ignore other translations for "I Have No Mouth"
            if lang_score(package.lang) == 0:
                continue

            installed = packaging.is_installed(package.name)
            if args.new and installed:
                continue

            if game not in tasks:
                tasks[game] = gamedata.construct_task(packaging=packaging)

            paths = []
            for path in tasks[game].iter_steam_paths((package,)):
                if path not in paths:
                    paths.append(path)
            if not paths and id not in owned:
                continue

            if game not in found_games:
                found_games.append(game)
            found_packages.append(FoundPackage(
                game,
                1 if package.type == 'full' else 2,
                package.name,
                installed,
                package.longname or gamedata.longname,
                paths
            ))
    if not found_games:
        logger.error('No Steam games found')
        return

    print('[x] = package is already installed')
    print('-' * 70 + '\n')
    found_packages = sorted(
        found_packages,
        key=lambda k: (k.game, k.game_type, k.longname),
    )
    for g in sorted(found_games):
        print(g)
        for p in found_packages:
            if p.game != g:
                continue
            print(
                '[%s] %-42s    %s' % (
                    'x' if p.installed else ' ',
                    p.package,
                    ascii_safe(p.longname)
                )
            )
            for path in p.paths:
                print(path)
            if not p.paths:
                print('<game owned but not installed/found>')
        print()

    if not args.new and not args.all:
        logger.info(
            'Please specify --all or --new to create desired packages.'
        )
        return

    preserve = (getattr(args, 'destination', None) is not None)
    install = getattr(args, 'install', True)
    if getattr(args, 'compress', None) is None:
        # default to not compressing if we aren't going to install it
        # anyway
        args.compress = preserve

    all_packages: set[str] = set()

    for shortname in sorted(found_games):
        task = tasks[shortname]
        task.verbose = getattr(args, 'verbose', False)
        task.save_downloads = args.save_downloads
        try:
            task.look_for_files(binary_executables=args.binary_executables)
        except BinaryExecutablesNotAllowed:
            continue
        except NoPackagesPossible:
            continue

        todo = list()
        for found_package in found_packages:
            if found_package.game == shortname and found_package.paths:
                todo.append(task.game.packages[found_package.package])

        if not todo:
            continue

        try:
            ready = task.prepare_packages(log_immediately=False,
                                          packages=todo)
        except NoPackagesPossible:
            logger.error('No package possible for %s.' % task.game.shortname)
            continue
        except DownloadsFailed:
            logger.error('Unable to complete any packages of %s'
                         ' because downloads failed.' % task.game.shortname)
            continue

        if args.destination is None:
            destination = workdir = tempfile.mkdtemp(prefix='gdptmp.')
        else:
            workdir = None
            destination = args.destination

        debs = task.build_packages(
            ready,
            compress=getattr(args, 'compress', True),
            destination=destination,
        )
        rm_rf(os.path.join(task.get_workdir(), 'tmp'))

        if preserve:
            for deb in debs:
                print('generated "%s"' % os.path.abspath(deb))
        all_packages = all_packages.union(debs)

    if not all_packages:
        logger.error('Unable to package any game.')
        if workdir:
            rm_rf(workdir)
        raise SystemExit(1)

    if install:
        packaging.install_packages(
            all_packages, args.install_method, args.gain_root_command,
        )
    if workdir:
        rm_rf(workdir)
