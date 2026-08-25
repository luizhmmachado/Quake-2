#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import io
import logging
import os
import struct
import re
from collections.abc import Iterator
from types import TracebackType
from typing import (BinaryIO, TypeVar)

from . import (StreamUnpackable, UnpackableEntry)

PathOrFile = TypeVar('PathOrFile',
                     str, bytes, int, io.BufferedReader, io.BytesIO)

logger = logging.getLogger(__name__)

# Arbitrary limit to avoid reading too much binary data if something goes wrong
MAX_LINE_LENGTH = 1024


class UmodSection:
    """Base class for [Sections] in a umod's manifest."""

    def __init__(self, name: str) -> None:
        # The name of the section, e.g. UTRequirement
        self.name = name
        # Sequence of UmodEntry
        self.entries: list[UmodEntry] = []
        # Stuff we didn't parse
        self.unparsed: list[tuple[str, str]] = []

    def _consume_line(
        self,
        umod: Umod,
        k: str,
        v: str
    ) -> None:
        raise NotImplementedError


class UmodEntryFile(io.BufferedIOBase):
    """File-like object allowing an embedded file to be read from a umod.

    Each Umod can currently have at most one UmodEntryFile open at a time.
    """

    def __init__(
        self,
        umod: Umod,
        entry: UmodEntry,
        offset: int,
        length: int,
    ) -> None:
        assert isinstance(umod.reader, io.BufferedIOBase)
        self.__umod: Umod = umod
        self.entry = entry
        self.__offset: int = offset
        self.__position: int | None = 0
        self.__length: int = length

    def read(
        self,
        size: int | None = -1,
    ) -> bytes:
        if self.__position is None:
            raise OSError('File closed')

        if (
            size is None
            or size < 0
            or size > (self.__length - self.__position)
        ):
            size = self.__length - self.__position

        if size <= 0:
            return b''

        ret = self.__umod.reader.read(size)
        self.__position += len(ret)

        return ret

    def read1(
        self,
        size: int | None = -1,
    ) -> bytes:
        """read1() is the same as read() for this class."""
        return self.read(size)

    def close(self) -> None:
        self.__position = None

    def _read_text_line(self) -> str:
        line = b';'

        # Lines starting with ; or // are comments.
        while line.startswith(b';') or line.startswith(b'//'):
            line = self.readline(MAX_LINE_LENGTH)

        if not line:
            raise ValueError('Unexpected end of file')
        elif not line.endswith(b'\r\n'):
            raise ValueError('Unterminated line: %r' % line)

        text_line = line[:-2].decode('windows-1252')
        return text_line


class UmodEntry(UnpackableEntry):
    """Base class for files and edit instructions in a umod."""

    def __init__(
        self,
        name: str,
        size: int,
        offset: int,
        toc_flags: int,
        manifest_flags: int,
    ) -> None:
        self._name = name.replace('\\', '/')
        self._size = size
        self.offset = offset
        self.toc_flags = toc_flags
        self.manifest_flags = manifest_flags

    def __repr__(self) -> str:
        return '<%s "%s" size=%d offset=%d toc_flags=%d manifest_flags=%d>' % (
            self.__class__.__name__, self.name, self.size, self.offset,
            self.toc_flags, self.manifest_flags)

    def __str__(self) -> str:
        return repr(self)

    @property
    def is_directory(self) -> bool:
        return False

    @property
    def is_regular_file(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return self._name

    @property
    def size(self) -> int:
        return self._size

    @property
    def type_indicator(self) -> str:
        if self.toc_flags or self.manifest_flags:
            if self.toc_flags == self.manifest_flags:
                return '-%d' % self.toc_flags
            else:
                return '-{toc=%d manifest=%d}' % (self.toc_flags,
                                                  self.manifest_flags)
        else:
            return '-r'


class UmodFileEntry(UmodEntry):
    """A file that can be unpacked from a umod."""
    pass


class UmodEditEntry(UmodEntry):
    """An instruction to edit a file by merging in content from the umod."""

    @property
    def is_regular_file(self) -> bool:
        return False

    @property
    def type_indicator(self) -> str:
        return 'e' + super(UmodEditEntry, self).type_indicator[1:]


_FILE_RE = re.compile(
    r'^[(]'
    r'Src="?([^,"]+)"?,'
    r'(?:Master="?[^,"]+"?,)?'
    r'(?:Lang=[a-z][a-z]t,)?'
    r'Size=([0-9]+)'
    r'(?:,Flags=([0-9]+))?'
    r'[)]$'
)
_COPY_RE = re.compile(
    r'^[(]'
    r'Src="?([^,"]+)"?,'
    r'(?:Master="?([^,"]+)"?)?,?'
    r'(?:Size=([^,]+))?,?'
    r'(?:Flags=([0-9]+))?,?'
    r'[)]$'
)


class UmodGroup(UmodSection):
    """A group of files and edit instructions.
    """

    def __init__(self, name: str) -> None:
        super(UmodGroup, self).__init__(name)
        self.entries: list[UmodEntry] = []

    def _consume_line(
        self,
        umod: Umod,
        k: str,
        v: str
    ) -> None:
        if k == 'File':
            m = _FILE_RE.match(v)

            if not m:
                raise ValueError('Unexpected value in File= line: %r' % v)

            name = m.group(1).replace('\\', '/')
            entry = umod.entries[name]
            assert entry.size == int(m.group(2)), entry.size

            if m.group(3) is not None:
                manifest_flags = int(m.group(3))
            else:
                manifest_flags = 0

            # replace placeholder
            umod.entries[name] = UmodFileEntry(
                    name, entry.size, entry.offset, entry.toc_flags,
                    manifest_flags)
            self.entries.append(umod.entries[name])

        elif k == 'Copy':
            m = _COPY_RE.match(v)

            if not m:
                raise ValueError('Unexpected value in Copy= line: %r' % v)

            assert m.group(2) is None or m.group(1) == m.group(2)
            name = m.group(1).replace('\\', '/')
            entry = umod.entries[name]

            if m.group(3) is not None:
                assert (entry.size == int(m.group(3)) or
                        name == 'System/Manifest.ini')

            if m.group(4) is not None:
                manifest_flags = int(m.group(4))
            else:
                manifest_flags = 0

            # replace placeholder
            umod.entries[name] = UmodEditEntry(
                name, entry.size, entry.offset, entry.toc_flags,
                manifest_flags)
            self.entries.append(umod.entries[name])

        elif k in ('AddIni',
                   'Backup',
                   'Delete',
                   'Ini',
                   'MasterPath',
                   'Optional',
                   'Selected',
                   'Visible',
                   'WinRegistry'):
            self.unparsed.append((k, v))

        else:
            raise ValueError('Unexpected key in group: %r (value %r)' % (k, v))


class UmodRequirement(UmodSection):
    def __init__(self, name: str) -> None:
        super(UmodRequirement, self).__init__(name)
        self.product: str | None = None
        self.version: str | None = None

    def _consume_line(
        self,
        umod: Umod,
        k: str,
        v: str,
    ) -> None:
        if k == 'Product':
            self.product = v
        elif k == 'Version':
            self.version = v
        elif k in ('DLLCheck',
                   'OldVersionNumber',
                   'OldVersionInstallCheck',
                   'MapCheck',
                   'TextureCheck',
                   'UCheck'):
            self.unparsed.append((k, v))
        else:
            raise ValueError('Unexpected key in requirement: %r (value %r)' %
                             (k, v))


class NotUmod(ValueError):
    pass


def _open(
    path_or_file: PathOrFile
) -> tuple[BinaryIO, str, int, int, int, int, bool]:
    if isinstance(path_or_file, (str, bytes, int)):
        close_file = True
        name = str(path_or_file)
        reader = open(path_or_file, 'rb')
    else:
        close_file = False
        reader = path_or_file

        if hasattr(path_or_file, 'name'):
            name = path_or_file.name
        else:
            name = repr(path_or_file)

        if reader.read(0) != b'':
            raise ValueError('%r is not open in binary mode' % reader)

        if not isinstance(reader, io.BufferedIOBase):
            reader = io.BufferedReader(reader)

    reader.seek(-20, os.SEEK_END)
    trailer_offset = reader.tell()
    block = reader.read(20)

    if len(block) != 20:
        raise NotUmod(
            '"%s" is not a .umod: unable to read 20 bytes at end' % name)

    magic, toc_offset, eof_offset, flags, checksum = struct.unpack(
        '<IIIII', block)

    if magic != 0x9fe3c5a3:
        raise NotUmod(
            '"%s" is not a .umod: magic number does not match' % name)

    if reader.tell() != eof_offset:
        raise NotUmod(
            '"%s" is not a .umod: length field does not match' % name)

    return (
        reader, name, toc_offset, trailer_offset, flags, checksum,
        close_file)


class Umod(StreamUnpackable):
    """Object representing an Unreal Tournament modification package,
    or an executable installer in a similar format.

    The API of this class is similar to tarfile.TarFile and zipfile.ZipFile.
    """

    def __init__(
        self,
        path_or_file: PathOrFile,
        mode: str = 'r'
    ) -> None:
        """Constructor.

        path_or_file may be a string or bytes object, a file descriptor,
        or a file object open in binary mode.
        """
        if mode != 'r':
            raise ValueError('Umod objects only support read access')

        self.product: str | None = None
        self.version: str | None = None
        self.sections: list[UmodRequirement | UmodGroup] = []
        self.requirements: dict[str, UmodRequirement] = {}
        self.groups: dict[str, UmodGroup] = {}
        self.entries: dict[str, UmodEntry] = {}
        self.entry_order: list[str] = []
        self.unparsed: list[tuple[str, str]] = []

        self.reader: BinaryIO
        self.name: str
        self.__close_file: bool
        self.reader, self.name, toc_offset, trailer_offset, flags, \
            checksum, self.__close_file = _open(path_or_file)

        self.reader.seek(toc_offset)

        n_entries = self.__read_compact_index()

        for i in range(n_entries):
            strlen = self.__read_compact_index()
            name = self.reader.read(strlen).decode('windows-1252')
            assert name[-1] == '\0', name
            name = name[:-1]
            offset, length, flags = struct.unpack('<III', self.reader.read(12))
            entry = UmodEntry(name, length, offset, flags, 0)
            self.entry_order.append(entry.name)
            self.entries[entry.name] = entry

        assert self.reader.tell() == trailer_offset
        manifest = self.open(self.entries['System/Manifest.ini'])
        first_line = manifest.readline()
        assert first_line == b'[Setup]\r\n', first_line

        expected_sections: dict[str, UmodRequirement | UmodGroup] = {}

        while True:
            line = manifest._read_text_line()

            # A blank line terminates the Setup section. The next line
            # is expected to be a requirement or group.
            if not line:
                break

            k, v = line.split('=', 1)

            if k == 'Product':
                self.product = v
            elif k == 'Version':
                self.version = v
            elif k == 'Requires':
                section = UmodRequirement(v)
                self.sections.append(section)
                self.requirements[v] = section
                expected_sections[v] = section
            elif k == 'Group':
                section_ = UmodGroup(v)
                self.sections.append(section_)
                self.groups[v] = section_
                expected_sections[v] = section_
            elif k in ('Archive',
                       'CdAutoPlay',
                       'Exe',
                       'IsMasterProduct',
                       'Language',
                       'Patch',
                       'PatchCdCheck',
                       'RefPath',
                       'SrcPath',
                       'Tree',
                       'MasterPath',
                       'Visible'):
                self.unparsed.append((k, v))
            else:
                raise ValueError('Unknown Umod [Setup] key: %r' % k)

        while expected_sections:
            line = manifest._read_text_line()

            if not line.startswith('[') or not line.endswith(']'):
                raise ValueError('Expected [*], got %r' % line)

            line = line[1:-1]

            if line not in expected_sections:
                logger.warning('Unexpected section [%s]' % line)

            self.__parse_section(manifest, expected_sections.pop(line, None))

        for x in self:
            assert isinstance(x, UmodEntry)
            assert x.__class__ != UmodEntry, x.name

    def __parse_section(
        self,
        manifest: UmodEntryFile,
        section: UmodSection | None
    ) -> None:
        while True:
            line = manifest._read_text_line()

            if not line:
                break

            k, v = line.split('=', 1)
            if section is None:
                logger.debug('%s=%s', k, v)
            else:
                section._consume_line(self, k, v)

    def __enter__(self) -> Umod:
        return self

    def __exit__(
        self,
        _et: type[BaseException] | None = None,
        _ev: BaseException | None = None,
        _tb: TracebackType | None = None
    ) -> None:
        if self.__close_file:
            self.reader.close()

    def open(self, member: str | UnpackableEntry) -> UmodEntryFile:
        """Open a binary file-like object for the given filename or UmodEntry.
        """
        if isinstance(member, str):
            entry = self.entries[member]
        else:
            assert isinstance(member, UmodEntry)
            entry = member

        self.reader.seek(entry.offset)
        return UmodEntryFile(self, entry, entry.offset, entry.size)

    def getinfo(self, name: str) -> UmodEntry:
        return self.entries[name]

    def infolist(self) -> list[UmodEntry]:
        return [x for x in self]

    def namelist(self) -> list[str]:
        return [x.name for x in self]

    def __iter__(self) -> Iterator[UmodEntry]:
        for name in self.entry_order:
            yield self.entries[name]

    def __read_compact_index(self) -> int:
        # http://wiki.beyondunreal.com/Legacy:Package_File_Format/Data_Details
        byte: int = self.reader.read(1)[0]
        negative = bool(byte & 0x80)
        more = bool(byte & 0x40)
        value = byte & 0x3f
        shift = 6

        while more:
            byte = self.reader.read(1)[0]

            # fifth byte contributes 8 bits 27..34 inclusive
            # (but we should never see that large an index in a umod)
            if shift >= 27:
                more = False
                value += (byte << shift)

            # second..fourth bytes contribute 7 bits 6..12, 13..19, 20. 26
            # inclusive
            more = bool(byte & 0x80)
            value += ((byte & 0x7f) << shift)
            shift += 7

        if negative:
            return -value
        return value

    @property
    def format(self) -> str:
        return 'umod'

    def seekable(self) -> bool:
        # umods are always seekable
        return True

    def printdir(self) -> None:
        print('# Product:', self.product)
        print('# Version:', self.version)
        print('# Requires:')

        for k, r in sorted(self.requirements.items()):
            print('# [%s] %r version %r' % (k, r.product, r.version))

        if 'System/Manifest.int' in self.entries:
            print('# Manifest text (international/English):')
            reader = self.open('System/Manifest.int')

            for line in reader:
                print('#', line.decode('windows-1252').rstrip('\r\n'))

        super(Umod, self).printdir()


def is_umod(path_or_file: PathOrFile) -> bool:
    try:
        _open(path_or_file)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output', '-o', help='extract to OUTPUT', default=None)
    parser.add_argument('umod')
    args = parser.parse_args()

    umod = Umod(args.umod)

    if args.output:
        umod.extractall(args.output)
    else:
        umod.printdir()
