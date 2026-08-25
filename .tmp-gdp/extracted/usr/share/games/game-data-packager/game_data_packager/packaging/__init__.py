#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from abc import (ABCMeta, abstractmethod)
import importlib
import os
import string
from collections.abc import (Iterable, Iterator, Sequence)
from typing import (TypedDict, TYPE_CHECKING, overload)

from ..data import (Package)

if TYPE_CHECKING:
    from typing import (NotRequired)
    from ..game import (GameData)
    from ..data import (PackageRelation)

Compression = bool | str | list[str]


class RecursiveExpansionMap(dict[str, str]):
    def __getitem__(self, k: str) -> str:
        v = super(RecursiveExpansionMap, self).__getitem__(k)
        return string.Template(v).substitute(self)


class PerPackageState:
    def __init__(
        self,
        package: Package,
        per_package_dir: str,
        download: bool,
    ) -> None:
        self.package = package

        # Installed files that will end up in DEBIAN/md5sums for
        # .deb packaging, e.g.
        # { 'usr/share/games/quake3-data/baseq3/pak0.pk3': '1197ca...' }
        self.md5sums: dict[str, str] = {}

        # Component for package, possibly modified: if the license
        # for a freely redistributable game is missing, we demote it from
        # main or non-free to local (i.e. non-distributable).
        self.component: str = package.component

        self.per_package_dir = per_package_dir
        self.destdir = os.path.join(per_package_dir, 'DESTDIR')

        self.lintian_overrides = set(package.lintian_overrides)

        # Flag from CLI, usefull for plugins
        self.download: bool = download


class PackagingSystem(metaclass=ABCMeta):
    ASSETS = '$datadir'
    BINDIR = '$prefix/bin'
    DATADIR = '$prefix/share'
    DOCDIR = '$datadir/doc'
    LICENSEDIR = '$datadir/doc'
    PREFIX = '/usr'
    CHECK_CMD: str
    INSTALL_CMD: list[str]

    # Generic tools needed to build packages
    BUILD_DEP: set[str] = set()

    # Exceptions to our normal heuristic for mapping a tool to a package:
    # the executable tool 'unzip' is in the unzip package, etc.
    #
    # Only exceptions need to be listed.
    #
    # 'NotImplemented' means that this dependency is not packaged by
    # the distro.
    PACKAGE_MAP: dict[str, str | None] = {}

    # Exceptions to our normal heuristic for mapping an abstract package name
    # to a package:
    #
    # - the library 'libfoo.so.0' is in a package that Provides libfoo.so.0
    #   (suitable for RPM)
    # - anything else is in the obvious package name
    RENAME_PACKAGES: dict[str, str] = {}

    # Map from Debian architecture name to packaging system's architecture
    # name.
    # We use Debian architectures as our internal representation, as it
    # - has the most architectures supported
    # - differentiates 'any' from 'all'
    # - is the most tested
    # Architectures not found in this map are assumed to match 1:1.
    ARCH_DECODE: dict[str, str] = dict()

    # Map from packaging system's architecture name to Debian
    # architecture name.
    # Architectures not found in this map are assumed to match 1:1.
    ARCH_ENCODE: dict[str, str] = dict()

    def __init__(self, architecture: str | None = None) -> None:
        # Always a dpkg architecture
        self._architecture: str | None = None

        if architecture is not None:
            self._architecture = self.ARCH_ENCODE.get(
                architecture, architecture,
            )

        # Always a set of dpkg architectures
        self._foreign_architectures: set[str] = set()
        # contexts to use when evaluating format- or distro-specific
        # dependencies, in order by preference
        self._contexts: Sequence[str] = ('generic',)

    def derives_from(self, context: str) -> bool:
        return context in self._contexts

    def read_architecture(self) -> str:
        arch = os.uname()[4]
        self._architecture = arch = {
            'armv7l': 'armhf',
            'armhfp': 'armhf',
            'aarch64': 'arm64',
            'i586': 'i386',
            'i686': 'i386',
            'x86_64': 'amd64',
        }.get(arch, arch)
        return arch

    def get_architecture(self, archs: str = '') -> str:
        '''
        Return the dpkg architecture most suitable for archs, which is
        a whitespace-separated string containing dpkg architectures.
        '''

        primary_arch = self._architecture
        if primary_arch is None:
            primary_arch = self.read_architecture()

        if archs:
            # In theory this should deal with wildcards like linux-any,
            # but it's unlikely to be relevant in practice.
            arch_seq = archs.split()

            if primary_arch in arch_seq or 'any' in arch_seq:
                return primary_arch

            for arch in arch_seq:
                if arch in self._foreign_architectures:
                    return arch

        return primary_arch

    def is_installed(self, package: str) -> bool:
        """Return boolean: is a package with the given name installed?"""
        return (self.current_version(package) is not None)

    def is_available(self, package: str) -> bool:
        """Return boolean: is a package with the given name available
        to apt or equivalent?
        """
        try:
            self.available_version(package)
        except Exception:
            return False
        else:
            return True

    @abstractmethod
    def current_version(self, package: str) -> str | None:
        """Return the version number of the given package as a string,
        or None.
        """
        raise NotImplementedError

    @abstractmethod
    def available_version(self, package: str) -> str | None:
        """Return the version number of the given package available in
        apt or equivalent, or raise an exception if unavailable.
        """
        raise NotImplementedError

    @abstractmethod
    def install_packages(
        self,
        packages: Iterable[str],
        method: str | None = None,
        gain_root: str = 'su',
        force: bool = False,
    ) -> None:
        """Install one or more packages (a list of filenames)."""
        raise NotImplementedError

    @overload
    def substitute(
        self,
        template: str | dict[str, str],
        package: str,
        **kwargs: str,
    ) -> str:
        ...

    @overload
    def substitute(
        self,
        template: None,
        package: str,
        **kwargs: str,
    ) -> None:
        ...

    def substitute(
        self,
        template: str | dict[str, str] | None,
        package: str,
        **kwargs: str,
    ) -> str | None:
        if isinstance(template, dict):
            for c in self._contexts:
                if c in template:
                    template = template[c]
                    break
            else:
                return None

        if template is None:
            return template

        if '$' not in template:
            return template

        return string.Template(template).substitute(
                RecursiveExpansionMap(
                    assets=self.ASSETS,
                    bindir=self.BINDIR,
                    datadir=self.DATADIR,
                    docdir=self.DOCDIR,
                    licensedir=self.LICENSEDIR,
                    pkgdocdir=self._get_pkgdocdir(package),
                    pkglicensedir=self._get_pkglicensedir(package),
                    prefix=self.PREFIX,
                    **kwargs))

    def get_libdir(self) -> str:
        return '/usr/lib'

    def _get_pkgdocdir(self, package: str) -> str:
        return '/'.join((self.DOCDIR, package))

    def _get_pkglicensedir(self, package: str) -> str:
        return '/'.join((self.LICENSEDIR, package))

    def format_relations(
        self,
        relations: Iterable[PackageRelation],
    ) -> Iterator[str]:
        """Yield a native dependency representation for this packaging system
        for each gdp.data.PackagingRelation in relations.
        """
        for pr in relations:
            if pr.contextual:
                for c in self._contexts:
                    if c in pr.contextual:
                        for x in self.format_relations([pr.contextual[c]]):
                            yield x

                        break
            else:
                yield self.format_relation(pr)

    @abstractmethod
    def format_relation(self, pr: PackageRelation) -> str:
        """Return a native dependency representation for this packaging system
        and the given gdp.data.PackagingRelation. It is guaranteed
        that pr.contextual is empty.
        """
        raise NotImplementedError

    def rename_package(self, dependency: str) -> str:
        """Given an abstract package name, return the corresponding
        package name in this packaging system.

        Abstract package names are mostly the same as for Debian,
        except that libraries are represented as libfoo.so.0.
        """
        return self.RENAME_PACKAGES.get(dependency, dependency)

    def package_for_tool(self, tool: str) -> str | None:
        """Given an executable name, return the corresponding
        package name in this packaging system.
        """
        return self.PACKAGE_MAP.get(tool, tool)

    def tool_for_package(self, package: str) -> str:
        """Given a package name, return the corresponding
        main/unique executable in this packaging system.
        """
        for k, v in self.PACKAGE_MAP.items():
            if v == package:
                return k
        return package

    def merge_relations(
        self,
        package: Package,
        rel: str
    ) -> set[str]:
        return set(self.format_relations(package.relations[rel]))

    def generate_description(
        self,
        game: GameData,
        package: Package,
        component: str | None = None
    ) -> tuple[str, list[str]]:

        longname = package.longname or game.longname
        if component is None:
            component = package.component

        if package.short_description is not None:
            short_desc = package.short_description
        elif package.section == 'games':
            short_desc = 'game %s for %s' % (package.data_type, longname)
        else:
            short_desc = longname

        if package.long_description is not None:
            return (short_desc, package.long_description.splitlines())

        long_desc = []
        long_desc.append('This package was built using game-data-packager.')

        if component == 'local':
            long_desc.append(
                'It contains proprietary game data and must not be '
                'redistributed.'
            )
        elif component == 'non-free':
            long_desc.append(
                'It contains proprietary game data that may be redistributed')
            long_desc.append('only under some conditions.')
        else:
            long_desc.append(
                'It contains free game data and may be redistributed.'
            )

        long_desc.append('')

        if package.description:
            for line in package.description.splitlines():
                long_desc.append(line.rstrip())
            long_desc.append('')

        if game.genre:
            long_desc.append(' Genre: ' + game.genre)

        if package.section == 'doc':
            long_desc.append(' Documentation: ' + longname)
        elif package.expansion_for and package.expansion_for in game.packages:
            game_name = (game.packages[package.expansion_for].longname
                         or game.longname)
            if game_name not in long_desc:
                long_desc.append(' Game: ' + game_name)
            if longname != game_name:
                long_desc.append(' Expansion: ' + longname)
        else:
            long_desc.append(' Game: ' + longname)

        copyright = package.copyright or game.copyright
        assert type(copyright) is str
        copyright = copyright.split(' ', 2)[2]
        if copyright not in long_desc:
            long_desc.append(' Published by: ' + copyright)

        engine = self.substitute(
                package.engine or game.engine,
                package.name)

        if engine and package.data_type not in ('music', 'documentation'):
            if long_desc[-1] != '':
                long_desc.append('')

            if '|' in engine:
                virtual = engine.split('|')[-1].strip()
                has_virtual = (virtual.split('-')[-1] == 'engine')
            else:
                has_virtual = False
            engine = engine.split('|')[0].split('(')[0].strip()
            if engine.startswith('gemrb'):
                engine = 'gemrb'
            if has_virtual:
                long_desc.append('Intended for use with some ' + virtual + ',')
                long_desc.append('such as for example: ' + engine)
            else:
                long_desc.append('Intended for use with: ' + engine)

        if package.used_sources:
            if long_desc[-1] != '':
                long_desc.append('')

            long_desc.append('Built from: ' + ', '.join(package.used_sources))

        return (short_desc, long_desc)

    def get_effective_architecture(self, package: Package) -> str:
        '''
        Return an architecture in this packaging system's representation.
        '''
        arch = package.architecture
        if arch != 'all':
            arch = self.get_architecture(arch)
        return self.ARCH_DECODE.get(arch, arch)

    @abstractmethod
    def build_package(
        self,
        per_package_state: PerPackageState,
        game: GameData,
        destination: str,
        compress: Compression = True,
    ) -> str:
        """Build the .deb or equivalent in destination, and return its
        filename.

        per_package_state.per_package_dir may be used as scratch space.
        It already contains a subdirectory named DESTDIR which has been
        populated with the files to be packaged
        (so it contains DESTDIR/usr, etc.)
        """
        raise NotImplementedError

    def available_version_at_least(
        self,
        package: str,
        desired: str,
        *,
        is_installed: bool | None = None
    ) -> bool:
        """Return true if the current or available version of the given
        package is at least a backport of the desired version.
        """
        # Stub implementation: we don't know how this packaging system
        # compares versions, so assume yes it is.
        return True


class NoPackaging(PackagingSystem):
    """
    A stub PackagingSystem used while checking consistency.
    """

    def __init__(self, architecture: str | None = None) -> None:
        super(NoPackaging, self).__init__(architecture=architecture)
        self._contexts = ('generic',)

    def current_version(self, package: str) -> str | None:
        return None

    def available_version(self, package: str) -> str | None:
        return None

    def install_packages(
        self,
        packages: Iterable[str],
        method: str | None = None,
        gain_root: str = 'su',
        force: bool = False,
    ) -> None:
        pass

    def build_package(
        self,
        per_package_state: PerPackageState,
        game: GameData,
        destination: str,
        compress: Compression = True,
    ) -> str:
        raise NotImplementedError

    def format_relation(self, pr: PackageRelation) -> str:
        assert not pr.contextual
        assert not pr.alternatives
        package = pr.package
        assert package is not None, str(pr)

        if pr.version is not None:
            return '%s (%s %s)' % (package, pr.version_operator, pr.version)

        return package


class PackagingTaskArgs(TypedDict):
    packaging: NotRequired[PackagingSystem | None]
    builder_packaging: NotRequired[PackagingSystem | None]


def get_packaging_system(
    format: str,
    distro: str | None = None,
    architecture: str | None = None
) -> PackagingSystem:
    mod = 'game_data_packager.packaging.{}'.format(format)
    packaging_system = importlib.import_module(mod).get_packaging_system(
        distro,
        architecture=architecture,
    )
    assert isinstance(packaging_system, PackagingSystem)
    return packaging_system


def get_native_packaging_system() -> PackagingSystem:
    # lazy import when actually needed
    from ..version import (FORMAT, DISTRO)
    return get_packaging_system(FORMAT, DISTRO)
