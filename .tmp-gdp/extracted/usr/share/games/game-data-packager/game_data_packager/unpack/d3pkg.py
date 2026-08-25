#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2024 Sébastien Noel <sebastien@twolife.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
from types import TracebackType

from . import (SimpleUnpackable)
from ..util import (mkdir_p)

PKG_MAGIC = 0x4f504b47

logger = logging.getLogger(__name__)


class D3Entry():
    """Data class for a file inside a Descent3 .pkg file."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.size = 0


class D3Pkg(SimpleUnpackable):
    """Object representing a Descent3 .pkg file."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.n_files = 0
        self.files = []
        self._parse_archive()

    def __enter__(self) -> D3Pkg:
        return self

    def __exit__(
        self,
        _et: type[BaseException] | None = None,
        _ev: BaseException | None = None,
        _tb: TracebackType | None = None
    ) -> None:
        pass

    def _parse_archive(self) -> None:
        reader = open(self.path, 'rb')
        archive_size = os.path.getsize(self.path)

        magic = int.from_bytes(reader.read(4), byteorder='little')
        if magic != PKG_MAGIC:
            raise ValueError(
                '"%s" is not a .pkg: magic number does not match' % self.path)

        self.n_files = int.from_bytes(reader.read(4), byteorder='little')
        logger.debug('%s contains %d files', self.path, self.n_files)

        nextFileStart = reader.tell()

        while nextFileStart < archive_size:
            reader.seek(nextFileStart)

            length = int.from_bytes(reader.read(4), byteorder='little')
            str_dirname = reader.read(length)[:-1].decode('windows-1252')
            str_dirname = str_dirname.replace("\\", "/")

            length = int.from_bytes(reader.read(4), byteorder='little')
            str_basename = reader.read(length)[:-1].decode('windows-1252')

            entry = D3Entry(os.path.join(str_dirname, str_basename))
            entry.size = int.from_bytes(reader.read(4), byteorder='little')
            logger.debug('Found %s - size: %d', entry.path, entry.size)

            # skip the next 8 bytes (checksum ?)
            reader.seek(8, 1)

            entry.offset = reader.tell()
            nextFileStart = entry.offset + entry.size

            self.files.append(entry)

        reader.close()

    def extractall(
        self,
        outdir: str,
    ) -> None:
        reader = open(self.path, 'rb')

        for entry in self.files:
            dest_file = os.path.join(outdir, entry.path)
            mkdir_p(os.path.dirname(dest_file))
            reader.seek(entry.offset)

            logger.debug('Extracting %s ...', dest_file)
            with open(dest_file, "wb") as f:
                f.write(reader.read(entry.size))
        reader.close()

    def printdir(self) -> None:
        for entry in self.files:
            print("%s @%d - size: %d" % (entry.path, entry.offset, entry.size))

    @property
    def format(self) -> str:
        return 'd3pkg'


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output', '-o', help='extract to OUTPUT', default=None)
    parser.add_argument('pkg')
    args = parser.parse_args()

    archive = D3Pkg(args.pkg)

    if args.output:
        archive.extractall(args.output)
    else:
        archive.printdir()
