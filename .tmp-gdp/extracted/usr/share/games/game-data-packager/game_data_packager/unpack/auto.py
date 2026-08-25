#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

import tarfile
import zipfile
from typing import BinaryIO

from . import (StreamUnpackable, TarUnpacker, ZipUnpacker)


def get_makeself_offset(
    archive: str,
    reader: BinaryIO | None = None,
) -> int:
    """Sniff Makeself archives, returning the offset to the embedded
    tar file, or 0 if not a makeself archive.

    http://megastep.org/makeself/
    """
    skip: int = 0
    line_number: int = 0
    trailer: bytes | None = None

    SHEBANG = bytes('/bin/sh', 'ascii')
    HEADER_V1 = bytes('# This script was generated using Makeself 1.', 'ascii')
    HEADER_V2 = bytes('# This script was generated using Makeself 2.', 'ascii')
    TRAILER_V1 = bytes('END_OF_STUB', 'ascii')
    TRAILER_V2 = bytes('eval $finish; exit $res', 'ascii')

    if reader is None:
        reader = open(archive, 'rb')

    for line in reader:
        line_number += 1
        skip += len(line)

        if line_number == 1 and SHEBANG not in line:
            return 0
        elif trailer:
            if trailer in line:
                return skip
        elif HEADER_V1 in line:
            trailer = TRAILER_V1
        elif HEADER_V2 in line:
            trailer = TRAILER_V2
        elif line_number > 3:
            return 0

    return 0


def automatic_unpacker(
    archive: str,
    reader: BinaryIO | None = None,
) -> StreamUnpackable | None:
    if reader is None:
        is_plain_file = True
        reader = open(archive, 'rb')
    else:
        is_plain_file = False

    if reader.seekable():
        skip = get_makeself_offset(archive, reader)

        if skip > 0:
            reader.seek(0)
            return TarUnpacker(
                archive, reader=reader, skip=skip, compression='gz')

        if zipfile.is_zipfile(reader):
            return ZipUnpacker(reader)

        if archive.endswith(('.umod', '.exe')):
            from .umod import (Umod, is_umod)
            if is_umod(reader):
                return Umod(reader)

    if is_plain_file and tarfile.is_tarfile(archive):
        return TarUnpacker(archive)

    return None
