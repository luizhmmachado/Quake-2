#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import errno
import os
import shlex
import shutil
import subprocess
import tarfile
import time
import zipfile
from abc import (ABCMeta, abstractmethod)
from collections.abc import (Collection, Iterator)
from types import TracebackType
from typing import (Any, BinaryIO)


class UnpackableEntry(metaclass=ABCMeta):
    """An entry in a StreamUnpackable.
    """
    @property
    @abstractmethod
    def is_directory(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_regular_file(self) -> bool:
        """True if the entry is a regular file. False if it is a
        directory, symlink, or some special thing like an instruction
        to patch some other file.
        """
        raise NotImplementedError

    @property
    def is_extractable(self) -> bool:
        """True if the entry is something that we can extract.

        The default implementation is that we can extract regular files.
        """
        return self.is_regular_file

    def get_symbolic_link_target(self) -> str | None:
        """Target of the symbolic link, or None if this is not a
        symbolic link.
        """
        return None

    @property
    def mtime(self) -> float | None:
        """The last-modification time, or None if unspecified."""
        return None

    @property
    @abstractmethod
    def name(self) -> str:
        """The absolute or relative filename, with Unix path separators."""
        raise NotImplementedError

    @property
    @abstractmethod
    def size(self) -> int:
        """The size in bytes."""
        raise NotImplementedError

    @property
    def type_indicator(self) -> str:
        """One or more ASCII symbols indicating the file type."""
        if self.is_directory:
            ret = 'd'
        elif self.is_regular_file:
            ret = '-'
        elif self.get_symbolic_link_target() is not None:
            ret = 'l'
        else:
            ret = '?'

        if self.is_extractable:
            ret += 'r'
        else:
            ret += '-'

        return ret


class SimpleUnpackable(metaclass=ABCMeta):
    """An archive in which entries can be inspected and extracted,
    but only all at once.
    """

    @property
    @abstractmethod
    def format(self) -> str:
        """Return the YAML "format" entry for this file.
        """
        raise NotImplementedError

    @abstractmethod
    def extractall(
        self,
        path: str,
        members: Collection[str] | None = None,
    ) -> None:
        """Extract all or most members of this archive to path.
        members is merely a hint: extracting more members than desired
        is allowed.
        """
        raise NotImplementedError

    def seekable(self) -> bool:
        """Return True if the unpacker is able to seek.
        """
        return False


class StreamUnpackable(SimpleUnpackable, metaclass=ABCMeta):
    """An archive in which entries can be inspected and extracted
    by iteration.
    """

    @abstractmethod
    def __iter__(self) -> Iterator[UnpackableEntry]:
        """Iterate through UnpackableEntry objects."""
        raise NotImplementedError

    @abstractmethod
    def open(self, member: str | UnpackableEntry) -> BinaryIO:
        """Open a binary file-like entry for the name or entry.
        """
        raise NotImplementedError

    def extract(
        self,
        member: str | UnpackableEntry,
        path: str | None = None,
    ) -> None:
        """Extract the given member from the archive into the given
        directory.
        """

        assert not isinstance(member, bytes), member

        if isinstance(member, str):
            filename = member
        else:
            filename = member.name

        reader = self.open(member)

        if not reader:
            raise ValueError('cannot open %s' % member)

        with reader:
            filename = filename.lstrip('/')

            while filename.startswith('../'):
                filename = filename[3:]
            filename = filename.replace('/../', '/')
            if filename.endswith('/..'):
                filename = filename[:-3]
            if filename.endswith('/'):
                filename = filename[:-1]
            if path is None:
                path = '.'

            dest = os.path.join(path, filename)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            try:
                os.remove(dest)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

            with open(dest, 'xb') as writer:
                shutil.copyfileobj(reader, writer)

    def extractall(
        self,
        path: str | None,
        members: Collection[str] | None = None,
    ) -> None:
        for entry in self:
            if entry.is_extractable:
                if members is None or entry.name in members:
                    self.extract(entry, path)

    def printdir(self) -> None:
        for entry in self:
            if entry.size is None:
                size = '?' * 9
            else:
                size = '%9s' % entry.size

            if entry.mtime is not None:
                mtime = time.strftime(
                    '%Y-%m-%d %H:%M:%S', time.gmtime(entry.mtime))
            else:
                mtime = '????-??-?? ??:??:??'

            print('%s %s %s %s' % (
                entry.type_indicator, size, mtime,
                shlex.quote(entry.name)))

    def seekable(self) -> bool:
        """Return True if the unpacker is able to seek.
        """
        return False

    def __enter__(self) -> StreamUnpackable:
        return self

    def __exit__(
        self,
        ex_type: type[BaseException] | None = None,
        ex_value: BaseException | None = None,
        ex_traceback: TracebackType | None = None
    ) -> None:
        pass


class WrapperUnpacker(StreamUnpackable):
    """Base class for a StreamUnpackable that wraps a TarFile-like object."""

    def __init__(self) -> None:
        # TODO: It must support open(), close() and iteration, but we don't
        # currently check that
        # + https://github.com/python/mypy/issues/3138
        self._impl: Any | None = None

    @abstractmethod
    def _wrap_entry(self, entry: Any) -> UnpackableEntry:
        raise NotImplementedError

    @abstractmethod
    def _is_entry(self, entry: Any) -> bool:
        raise NotImplementedError

    def __enter__(self) -> WrapperUnpacker:
        return self

    def __exit__(
        self,
        ex_type: type[BaseException] | None = None,
        ex_value: BaseException | None = None,
        ex_traceback: TracebackType | None = None
    ) -> None:
        if self._impl is not None:
            self._impl.close()
            self._impl = None

    def __iter__(self) -> Iterator[UnpackableEntry]:
        assert self._impl is not None, 'unpacker context not entered'

        for entry in self._impl:
            yield self._wrap_entry(entry)

    def open(self, entry: Any) -> BinaryIO:
        assert self._impl is not None, 'unpacker context not entered'
        assert self._is_entry(entry)
        contents = self._impl.open(entry.impl)
        assert contents is not None
        return contents


class TarEntry(UnpackableEntry):
    __slots__ = 'impl'

    def __init__(self, impl: tarfile.TarInfo) -> None:
        self.impl = impl

    @property
    def is_directory(self) -> bool:
        return self.impl.isdir()

    @property
    def is_regular_file(self) -> bool:
        return self.impl.isfile()

    @property
    def mtime(self) -> float:
        return self.impl.mtime

    @property
    def name(self) -> str:
        return self.impl.name

    @property
    def size(self) -> int:
        return self.impl.size

    def get_symbolic_link_target(self) -> str | None:
        if self.impl.issym():
            return self.impl.linkname
        else:
            return None

    @property
    def type_indicator(self) -> str:
        """One or more ASCII symbols indicating the file type."""
        if self.impl.isdir():
            ret = 'd'
        elif self.impl.isfile():
            ret = '-'
        elif self.impl.issym():
            ret = 'l'
        else:
            ret = '?<%r>' % self.impl.type

        if self.is_extractable:
            ret += 'r'
        else:
            ret += '-'

        return ret


class DpkgDebUnpacker(WrapperUnpacker):
    def __init__(self, path: str) -> None:
        self._path = path
        self._fsys_process: Any | None = None  # ?

    def __enter__(self) -> DpkgDebUnpacker:
        self._fsys_process = subprocess.Popen(
            ['dpkg-deb', '--fsys-tarfile', self._path],
            stdout=subprocess.PIPE,
        ).__enter__()
        assert self._fsys_process is not None
        self._impl = tarfile.open(
            self._path, mode='r|', fileobj=self._fsys_process.stdout,
        ).__enter__()
        return self

    def __exit__(
        self,
        ex_type: type[BaseException] | None = None,
        ex_value: BaseException | None = None,
        ex_traceback: TracebackType | None = None
    ) -> None:
        if self._impl is not None:
            self._impl.__exit__(ex_type, ex_value, ex_traceback)
            self._impl = None

        if self._fsys_process is not None:
            self._fsys_process.__exit__(ex_type, ex_value, ex_traceback)
            self._fsys_process = None

    @property
    def format(self) -> str:
        return 'deb'

    def open(self, entry: Any) -> BinaryIO:
        assert isinstance(entry, TarEntry)
        assert type(self._impl) is tarfile.TarFile
        contents = self._impl.extractfile(entry.impl)
        assert contents is not None
        return contents

    def _is_entry(self, entry: Any) -> bool:
        return isinstance(entry, TarEntry)

    def _wrap_entry(self, entry: tarfile.TarInfo) -> UnpackableEntry:
        return TarEntry(entry)


class TarUnpacker(WrapperUnpacker):
    def __init__(
        self,
        name: str,
        reader: BinaryIO | None = None,
        compression: str = '*',
        skip: int = 0,
    ) -> None:
        super(TarUnpacker, self).__init__()
        self.skip = skip
        self.compression = compression

        if reader is None:
            reader = open(name, 'rb')

        if skip:
            discard = reader.read(skip)
            assert len(discard) == skip

        self._impl = tarfile.open(
            name, mode='r|' + compression, fileobj=reader)

    @property
    def format(self) -> str:
        return 'tar.' + self.compression

    def open(self, entry: Any) -> BinaryIO:
        assert isinstance(entry, TarEntry)
        assert type(self._impl) is tarfile.TarFile
        contents = self._impl.extractfile(entry.impl)
        assert contents is not None
        return contents

    def _is_entry(self, entry: Any) -> bool:
        return isinstance(entry, TarEntry)

    def _wrap_entry(self, entry: tarfile.TarInfo) -> UnpackableEntry:
        return TarEntry(entry)


class ZipEntry(UnpackableEntry):
    __slots__ = 'impl'

    def __init__(self, impl: zipfile.ZipInfo) -> None:
        self.impl = impl

    @property
    def is_directory(self) -> bool:
        return self.name.endswith('/')

    @property
    def is_regular_file(self) -> bool:
        return not self.name.endswith('/')

    @property
    def mtime(self) -> float:
        return time.mktime(self.impl.date_time + (0, 0, -1))

    @property
    def name(self) -> str:
        return self.impl.filename

    @property
    def size(self) -> int:
        return self.impl.file_size


class ZipUnpacker(WrapperUnpacker):
    def __init__(
        self,
        file_or_name: str | BinaryIO
    ) -> None:
        super(ZipUnpacker, self).__init__()
        if hasattr(file_or_name, 'seekable') and not file_or_name.seekable():
            self.__seekable = False
        else:
            # zip files based on an on-disk file are seekable
            self.__seekable = True

        self._impl = zipfile.ZipFile(file_or_name, 'r')

    def __iter__(self) -> Iterator[ZipEntry]:
        assert type(self._impl) is zipfile.ZipFile
        for entry in self._impl.infolist():
            yield ZipEntry(entry)

    def _is_entry(self, entry: Any) -> bool:
        return isinstance(entry, ZipEntry)

    def _wrap_entry(self, entry: zipfile.ZipInfo) -> UnpackableEntry:
        return ZipEntry(entry)

    @property
    def format(self) -> str:
        return 'zip'

    def seekable(self) -> bool:
        return self.__seekable
