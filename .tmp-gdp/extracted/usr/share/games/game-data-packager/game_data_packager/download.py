#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2017 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
import random
import urllib.request
from typing import (cast, TypedDict, TYPE_CHECKING)

from .data import (HashedFile)
from .paths import (ETCDIR)
from .util import (AGENT, mkdir_p)

if TYPE_CHECKING:
    from .data import (ProgressFactory, WantedFile)

logging.basicConfig()
logger = logging.getLogger(__name__)


class NotDownloadable(Exception):
    pass


class OutOfSpace(Exception):
    pass


class Downloader:
    def __init__(
        self,
        progress_factory: ProgressFactory | None = None
    ) -> None:
        self.download_failed: set[str] = set()

        self.progress_factory: ProgressFactory
        if progress_factory is None:
            self.progress_factory = lambda info=None: None
        else:
            self.progress_factory = progress_factory

    @staticmethod
    def choose_mirror(wanted: WantedFile) -> list[str]:
        assert type(wanted.download) is not None

        mirrors = []
        mirror = os.environ.get('GDP_MIRROR')
        if mirror:
            if mirror.startswith('/'):
                mirror = 'file://' + mirror
            elif mirror.split(':')[0] not in ('http', 'https', 'ftp', 'file'):
                mirror = 'http://' + mirror
            if not mirror.endswith('/'):
                mirror = mirror + '/'

        if type(wanted.download) is str:
            if not mirror:
                return [wanted.download]
            url_basename = os.path.basename(wanted.download)
            if '?' not in url_basename:
                mirrors.append(mirror + url_basename)
            wanted.name = wanted.name.replace(' ', '%20')
            if wanted.name != url_basename and '?' not in wanted.name:
                mirrors.append(mirror + wanted.name)
            mirrors.append(wanted.download)
            return mirrors

        class DownloadDetails(TypedDict):
            path: str
            name: str

        assert type(wanted.download) is dict
        for mirror_list, details_ in wanted.download.items():
            details = cast(DownloadDetails, details_)
            try:
                f = open(os.path.join(ETCDIR, mirror_list), encoding='utf-8')
                for line in f:
                    url = line.strip()
                    if not url:
                        continue
                    if url.startswith('#'):
                        continue
                    if details.get('path', '.') != '.':
                        if not url.endswith('/'):
                            url = url + '/'
                        url = url + details['path']
                    if not url.endswith('/'):
                        url = url + '/'
                    url = url + details.get('name', wanted.filename)
                    mirrors.append(url)
            except OSError:
                logger.warning(
                    'Could not open mirror list "%s"', mirror_list,
                    exc_info=True,
                )
        random.shuffle(mirrors)
        if mirror:
            if mirrors and '?' not in mirrors[0]:
                mirrors.insert(0, mirror + os.path.basename(mirrors[0]))
            elif '?' not in wanted.name:
                mirrors.insert(0, mirror + wanted.name)
        if not mirrors:
            logger.error('Could not select a mirror for "%s"', wanted.name)
            return []
        return mirrors

    def download(
        self,
        wanted: WantedFile,
        dest: str,
    ) -> tuple[str, HashedFile]:
        logger.debug('trying to download %s...', wanted.name)
        assert type(wanted.size) is int
        statvfs = os.statvfs(dest)
        if wanted.size > statvfs.f_frsize * statvfs.f_bavail:
            logger.error(
                "Out of space on %s, can't download %s.",
                dest, wanted.name,
            )
            self.download_failed |= set(self.choose_mirror(wanted))
            raise OutOfSpace

        urls = self.choose_mirror(wanted)
        for url in urls:
            if url in self.download_failed:
                logger.debug('... no, it already failed')
                continue

            logger.debug('... %s', url)

            tmp = None
            try:
                rf = urllib.request.urlopen(
                    urllib.request.Request(
                        url, headers={'User-Agent': AGENT},
                    )
                )
                if rf is None:
                    continue

                try:
                    size = int(rf.info().get('Content-Length'))
                except Exception:
                    size = None
                if size and size != wanted.size:
                    logger.warning("File doesn't have expected size"
                                   " (%s vs %s), skipping %s",
                                   size, wanted.size, url)
                    self.download_failed.add(url)
                    continue

                tmp = os.path.join(dest, wanted.name)
                mkdir_p(os.path.dirname(tmp))

                with open(tmp, 'wb') as wf:
                    logger.info('downloading %s', url)
                    hf = HashedFile.from_file(
                        url, rf, wf,
                        size=wanted.size,
                        progress=self.progress_factory()
                    )

                return tmp, hf
            except Exception as e:
                logger.warning(
                    'Failed to download "%s": %s', url, e,
                )
                self.download_failed.add(url)
                if tmp is not None:
                    os.remove(tmp)
        else:
            raise NotDownloadable


if __name__ == '__main__':
    # Usage:
    # GDP_UNINSTALLED=1 \
    # PYTHONPATH=$(pwd) \
    # python3 -m game_data_packager.download \
    # unreal skaarj_logo.jpg .

    import sys

    from .game import (load_games)

    game_ = sys.argv[1]
    filename = sys.argv[2]
    dest = sys.argv[3]

    games = load_games(game=game_)
    game = games[game_]
    game.load_file_data()
    wanted = game.files[filename]

    path, hasher = Downloader().download(wanted, dest)

    if path is None:
        logger.error('Unable to download "%s"', filename)
    else:
        logger.info('Downloaded "%s" to "%s"', filename, path)

        if hasher.size != wanted.size:
            logger.info('size: %s, expected %s', hasher.size, wanted.size)

        if hasher.md5 != wanted.md5:
            logger.info('md5: %s, expected %s', hasher.md5, wanted.md5)

        if hasher.sha1 != wanted.sha1:
            logger.info('sha1: %s, expected %s', hasher.sha1, wanted.sha1)

        if hasher.sha256 != wanted.sha256:
            logger.info(
                'sha256: %s, expected %s', hasher.sha256, wanted.sha256)
