#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import hashlib
import io
import yaml
from collections.abc import (Iterable)
from types import TracebackType
from typing import (Any, BinaryIO, Literal, Protocol)

from .version import (GAME_PACKAGE_VERSION)


class ProgressCallback:
    """API for a progress report."""

    def __call__(
        self,
        done: int | None = None,
        total: int | None = None,
        checkpoint: bool = False,
    ) -> None:
        """Update progress: we have done @done bytes out of @total
        (None if unknown).

        If @checkpoint is True, it is a hint that this particular
        update is important (for instance the end of a file).
        """
        pass

    def __enter__(self) -> ProgressCallback:
        return self

    def __exit__(
        self,
        et: type[BaseException] | None = None,
        ev: BaseException | None = None,
        tb: TracebackType | None = None,
    ) -> None:
        pass


class ProgressFactory(Protocol):
    def __call__(
        self,
        info: str | None = None,
    ) -> ProgressCallback | None:
        ...


class HashedFile:
    def __init__(self, name: str) -> None:
        self.name: str = name
        self._md5: str | None = None
        self._sha1: str | None = None
        self._sha256: str | None = None
        self._size: int | None = None
        self.skip_hash_matching: bool = False

    @classmethod
    def from_file(
        cls,
        name: str,
        f: BinaryIO,
        write_to: BinaryIO | None = None,
        size: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> HashedFile:
        return cls.from_concatenated_files(name, [f], write_to, size, progress)

    @classmethod
    def from_concatenated_files(
        cls,
        name: str,
        fs: Iterable[BinaryIO],
        write_to: BinaryIO | None = None,
        size: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> HashedFile:
        md5 = hashlib.new('md5')
        sha1 = hashlib.new('sha1')
        sha256 = hashlib.new('sha256')
        done = 0

        if progress is None:
            progress = ProgressCallback()

        with progress:
            for f in fs:
                while True:
                    progress(done, size)

                    blob = f.read(io.DEFAULT_BUFFER_SIZE)

                    if not blob:
                        progress(done, size, checkpoint=True)
                        break

                    done += len(blob)

                    md5.update(blob)
                    sha1.update(blob)
                    sha256.update(blob)
                    if write_to is not None:
                        write_to.write(blob)

        self = cls(name)
        self.md5 = md5.hexdigest()
        self.sha1 = sha1.hexdigest()
        self.sha256 = sha256.hexdigest()
        self._size = done
        return self

    @property
    def have_hashes(self) -> bool:
        return ((self.md5 is not None) or
                (self.sha1 is not None) or
                (self.sha256 is not None))

    # https://realpython.com/python-type-self/
    def matches(self, other: HashedFile) -> bool:
        matched = False

        if self.skip_hash_matching or other.skip_hash_matching:
            return False

        if None not in (self.size, other.size):
            # Don't set matched: the size is only a very weak way to
            # compare for equality
            if self.size != other.size:
                return False

        if None not in (self.md5, other.md5):
            matched = True
            if self.md5 != other.md5:
                return False

        if None not in (self.sha1, other.sha1):
            matched = True
            if self.sha1 != other.sha1:
                return False

        if None not in (self.sha256, other.sha256):
            matched = True
            if self.sha256 != other.sha256:
                return False

        if not matched:
            raise ValueError(
                (
                    'Unable to determine whether checksums match:\n'
                    '%s has:\n'
                    '  size:   %s\n'
                    '  md5:    %s\n'
                    '  sha1:   %s\n'
                    '  sha256: %s\n'
                    '%s has:\n'
                    '  size:   %s\n'
                    '  md5:    %s\n'
                    '  sha1:   %s\n'
                    '  sha256: %s\n'
                ) % (
                    self.name,
                    self.size,
                    self.md5,
                    self.sha1,
                    self.sha256,
                    other.name,
                    other.size,
                    other.md5,
                    other.sha1,
                    other.sha256,
                )
            )

        return True

    @property
    def size(self) -> int | None:
        return self._size

    @property
    def md5(self) -> str | None:
        return self._md5

    @md5.setter
    def md5(self, value: str) -> None:
        if self._md5 is not None and value != self._md5:
            raise AssertionError(
                'trying to set md5 of "%s" to both %s and %s'
                % (self.name, self._md5, value)
            )
        self._md5 = value

    @property
    def sha1(self) -> str | None:
        return self._sha1

    @sha1.setter
    def sha1(self, value: str) -> None:
        if self._sha1 is not None and value != self._sha1:
            raise AssertionError(
                'trying to set sha1 of "%s" to both %s and %s'
                % (self.name, self._sha1, value)
            )
        self._sha1 = value

    @property
    def sha256(self) -> str | None:
        return self._sha256

    @sha256.setter
    def sha256(self, value: str) -> None:
        if self._sha256 is not None and value != self._sha256:
            raise AssertionError(
                'trying to set sha256 of "%s" to both %s and %s'
                % (self.name, self._sha256, value)
            )
        self._sha256 = value


class WantedFile(HashedFile):
    def __init__(self, name: str) -> None:
        super(WantedFile, self).__init__(name)
        self.alternatives: list[str] = []
        self.architecture: str = 'all'
        self.doc: bool = False
        self._distinctive_name: bool | None = None
        self.distinctive_size: bool = False
        self._download: None | str | dict[str, str] = None
        self.executable: bool = False
        self.filename: str = name.split('?')[0]
        self.ignorable: bool = False
        self.install_as: str = self.filename
        self._install_to: str | None = None
        self.license: bool = False
        self._look_for: set[str] | None = None
        self._provides: set[str] = set()
        self.provides_files: set[WantedFile] = set()
        self._size: int | None = None
        self.unpack: dict[str, str | int | list[str] | bool] | None = None
        self.unsuitable: str | None = None

    def apply_group_attributes(self, attributes: dict[str, Any]) -> None:
        for k, v in attributes.items():
            assert hasattr(self, k)
            setattr(self, k, v)

    @property
    def distinctive_name(self) -> bool:
        if self._distinctive_name is not None:
            return self._distinctive_name
        return not self.license

    @distinctive_name.setter
    def distinctive_name(self, value: bool) -> None:
        self._distinctive_name = value

    @property
    def download(self) -> None | str | dict[str, str]:
        return self._download

    @download.setter
    def download(self, value: None | str | dict[str, str]) -> None:
        if isinstance(value, dict):
            for mirror_list, details in value.items():
                for k in details:
                    assert k in ('path', 'name'), (self, value, k)

        elif isinstance(value, str):
            assert value.startswith(
                ('http://', 'https://', 'ftp://')
            ), (self, value)

        elif value is not None:
            raise AssertionError(
                '%r.download not None, str or dict: %r',
                self, value)

        self._download = value

    @property
    def install_to(self) -> str | None:
        if self._install_to is not None:
            return self._install_to
        if self.doc:
            return '$pkgdocdir'
        if self.license:
            return '$pkglicensedir'
        return None

    @install_to.setter
    def install_to(self, value: str) -> None:
        self._install_to = value

    @property
    def look_for(self) -> set[str]:
        if self.alternatives:
            return set([])
        if self._look_for is not None:
            return self._look_for
        return set([self.filename.lower(), self.install_as.lower()])

    @look_for.setter
    def look_for(self, value: str | Iterable[str]) -> None:
        if isinstance(value, str):
            value = (value,)
        self._look_for = set(x.lower() for x in value)

    @property
    def size(self) -> int | None:
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        if self._size is not None and value != self._size:
            raise AssertionError(
                'trying to set size of "%s" to both %d and %d'
                % (self.name, self._size, value)
            )
        self._size = int(value)

    @property
    def provides(self) -> set[str]:
        return self._provides

    @provides.setter
    def provides(
        self,
        value: Iterable[str],
    ) -> None:
        self._provides = set(value)

    def to_data(
        self,
        expand: bool = True,
    ) -> dict[str, Any]:
        ret: dict[str, Any] = {}

        if expand:
            ret['name'] = self.name

        for k in (
                'alternatives',
                'skip_hash_matching',
                ):
            v = getattr(self, k)
            if v:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        provides = set()

        if expand:
            for f in self.provides_files:
                if not f.ignorable:
                    provides.add(f.name)
        else:
            for filename in self.provides:
                provides.add(filename)

        if provides:
            ret['provides'] = sorted(provides)

        for k in (
                'download',
                'unsuitable',
                'unpack',
                ):
            v = getattr(self, k)
            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        if expand:
            for k in (
                    'md5',
                    'sha1',
                    'sha256',
                    'size',
                    ):
                v = getattr(self, k)
                if v is not None:
                    ret[k] = v

        for k in (
                'distinctive_size',
                'doc',
                'executable',
                'license',
                ):
            if getattr(self, k):
                ret[k] = True

        for k, default in (
            ('architecture', 'all'),
            ('install_as', self.filename),
        ):
            v = getattr(self, k)

            if v != default:
                ret[k] = v

        for k in (
                'distinctive_name',
                'install_to',
                'look_for',
                ):
            if expand:
                # use derived value
                v = getattr(self, k)
            else:
                v = getattr(self, '_' + k)

            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        return ret


class PackageRelation:
    def __init__(self, rel: str | dict[str, str]) -> None:
        assert isinstance(rel, str) or isinstance(rel, dict)
        assert ',' not in rel

        self.package = None
        self.version: str | None = None
        self.version_operator: str | None = None
        self.alternatives: list['PackageRelation'] = []
        self.contextual: dict[str, 'PackageRelation'] = {}

        if isinstance(rel, dict):
            for context, specific in rel.items():
                assert isinstance(context, str), context
                assert isinstance(specific, str), specific
                self.contextual[context] = PackageRelation(specific)
        elif '|' in rel:
            self.alternatives = [
                PackageRelation(bit.strip()) for bit in rel.split('|')
            ]
        else:
            for operator in '>=', '>>', '<=', '<<', '=':
                if operator in rel:
                    package, version = rel.split(operator)
                    package = package.rstrip('(')
                    self.package = package.strip()
                    version = version.rstrip(')')
                    self.version = version.strip()
                    self.version_operator = operator
                    break
            else:
                self.package = rel

                assert self.package.strip() == self.package, repr(self.package)

    def to_data(self) -> str | dict[str, str]:
        if self.contextual:
            data = {}

            for context, specific in self.contextual.items():
                item = specific.to_data()
                assert isinstance(item, str), item
                data[context] = item

            return data

        if self.alternatives:
            items = []

            for alt in self.alternatives:
                item = alt.to_data()
                assert isinstance(item, str), item
                items.append(item)

            return ' | '.join(items)

        return str(self)

    def __str__(self) -> str:
        if self.contextual:
            ret = []
            for context, specific in self.contextual.items():
                ret.append(repr(context) + ': ' + repr(str(specific)))
            ret.sort()
            return '{' + ', '.join(ret) + '}'

        if self.alternatives:
            return ' | '.join([str(s) for s in self.alternatives])

        if self.version is None:
            return '%s' % self.package

        return '%s (%s %s)' % (
            self.package, self.version_operator, self.version,
        )

    def __repr__(self) -> str:
        return 'PackageRelation(' + repr(self.to_data()) + ')'


class YamlLiteral(str):
    @classmethod
    def to_yaml(cls, dumper: Any, data: YamlLiteral) -> Any:
        return dumper.represent_scalar(
            'tag:yaml.org,2002:str', data, style='|',
        )


yaml.add_representer(YamlLiteral, YamlLiteral.to_yaml)


class FileGroup:
    RECURSIVELY_APPLIED = (
        'architecture',
        'distinctive_name',
        'doc',
        'executable',
        'ignorable',
        'install_to',
        'license',
        'unsuitable',
    )
    # WIP, mypy won't understand the 'setattr()'
    doc: bool
    ignorable: bool
    install_to: str
    license: bool

    def __init__(self, name: str) -> None:
        self.name = name
        self.group_members: set[str] = set()

        # Attributes to apply to every member of this group.
        for attr in self.RECURSIVELY_APPLIED:
            setattr(self, attr, None)

    def apply_group_attributes(
        self,
        other: WantedFile | FileGroup
    ) -> None:
        assert isinstance(other, WantedFile) or isinstance(other, FileGroup)

        for attr in self.RECURSIVELY_APPLIED:
            assert hasattr(other, attr)
            value = getattr(self, attr)

            if value is not None:
                setattr(other, attr, value)

    def to_data(
        self,
        expand: bool = True,
        files: dict[str, WantedFile] | None = None,
        include_ignorable: bool = False,
    ) -> dict[str, Any]:
        ret: dict[str, Any] = {}

        for attr in self.RECURSIVELY_APPLIED:
            value = getattr(self, attr)

            if value is not None:
                ret[attr] = value

        if self.group_members:
            if files is None:
                ret['group_members'] = sorted(self.group_members)
            else:
                group_members = []

                for name in sorted(self.group_members):
                    prefix = ''

                    if name in files:
                        f = files[name]
                        size: Any = f.size
                        md5: Any = f.md5

                        if f.ignorable:
                            if not include_ignorable:
                                continue

                            prefix = '.'
                    else:
                        size = '_'
                        md5 = '_'

                    if size is None:
                        size = '_'

                    if md5 is None:
                        md5 = '_'

                    group_members.append(
                        '%s%-9s %s %s\n' % (prefix, size, md5, name))

                ret['group_members'] = YamlLiteral(''.join(group_members))

        return ret


class Package:
    def __init__(self, name: str, data: dict[str, Any]) -> None:
        # The name of the binary package
        self.name = name

        # Other names for this binary package
        self._aliases: set[str] = set()

        # Names of relative packages
        self.demo_for: set[str] = set()
        self._better_versions: set[str] = set()
        self.expansion_for: str | None = None
        self.multi_arch = None
        # use this for games with demo_for/better_version/provides
        self.mutually_exclusive: bool = False
        # expansion for a package outside of this yaml file;
        # may be another GDP package or a package not made by GDP
        self.expansion_for_ext: str | None = None

        self.relations: dict[str, list[PackageRelation]] = dict(
            breaks=[],
            build_depends=[],
            conflicts=[],
            depends=[],
            provides=[],
            recommends=[],
            replaces=[],
            suggests=[],
        )

        # The optional marketing name of this version
        self.longname: str | None = None

        # This word is used to build package description
        # 'data' / 'music' / 'documentation' / 'PWAD' / 'IWAD' / 'binaries'
        self.data_type: str = 'data'

        # if not None, override the description completely
        self.long_description: str | None = None

        # extra blurb of text added to .deb long description
        self.description: str | None = None

        # first line of .deb description, or None to construct one from
        # longname
        self.short_description: str | None = None

        # This optional value will overide the game global copyright
        self.copyright: str | None = None

        # A blurb of text that is used to build debian/copyright
        self.copyright_notice: str | None = None

        # Languages, list of ISO-639 codes
        self.langs: list[str] = ['en']

        # Where we install files.
        # For instance, if this is 'usr/share/games/quake3' and we have
        # a WantedFile with install_as='baseq3/pak1.pk3' then we would
        # put 'usr/share/games/quake3/baseq3/pak1.pk3' in the .deb.
        # The default is 'usr/share/games/' plus the binary package's name.
        if name.endswith('-data'):
            self.default_install_to = '$assets/' + name[:len(name) - 5]
        else:
            self.default_install_to = '$assets/' + name

        self.install_to: str = self.default_install_to

        # If true, this package is allowed to be empty
        self.empty: bool = False

        # symlink => real file (the opposite way round that debhelper does it,
        # because the links must be unique but the real files are not
        # necessarily)
        self.symlinks: dict[str, str] = {}

        # online stores metadata
        self.steam: dict[str, Any] = {}
        self.gog: dict[str, Any] | Literal[False] = {}
        self.origin: dict[str, Any] = {}
        self.url_misc: str | None = None

        # overide the game engine when needed
        self.engine: str | None = None

        # expansion's dedicated Wiki page, appended to GameData.wikibase
        self.wiki: str | None = None

        # set of names of WantedFile instances to be installed
        self._install: set[str] = set()

        # set of names of WantedFile instances to be optionally installed
        self._optional: set[str] = set()

        # set of names of WantedFile instances that indicate that we want this
        self.activated_by: set[str] = set()

        # set of WantedFile instances for install, with groups expanded
        # only available after load_file_data()
        self.install_files: set[WantedFile] | None = None
        # set of WantedFile instances for optional, with groups expanded
        self.optional_files: set[WantedFile] | None = None
        # set of names of WantedFile instances that indicate that we want this
        self.activated_by_files: set[WantedFile] | None = None

        self.version = GAME_PACKAGE_VERSION

        # CD audio stuff from YAML
        self.rip_cd: dict[str, Any] = {}

        # possible override for disks: tag at top level
        # e.g.: Feeble Files had 2-CD releases too
        self.disks: int | None = None

        # Debian architecture(s)
        self.architecture: str = 'all'

        # Component (archive area): main, contrib, non-free, local
        # We use "local" to mean "not distributable"; the others correspond
        # to components in the Debian archive
        self.component: str = 'local'
        self.section: str = 'games'

        # show output of external tools?
        self.verbose: bool = False

        # archives actually used to built a package
        self.used_sources: set[str] = set()

        # Lintian overrides
        self._lintian_overrides: set[str] = set()

        for k in (
                'aliases',
                'architecture',
                'better_versions',
                'component',
                'copyright',
                'copyright_notice',
                'data_type',
                'description',
                'disks',
                'empty',
                'engine',
                'expansion_for',
                'expansion_for_ext',
                'gog',
                'install_to',
                'lang',
                'langs',
                'lintian_overrides',
                'long_description',
                'longname',
                'multi_arch',
                'mutually_exclusive',
                'origin',
                'rip_cd',
                'section',
                'short_description',
                'steam',
                'symlinks',
                'url_misc',
                'wiki',
                ):
            if k in data:
                setattr(self, k, data[k])

        if 'better_version' in data:
            assert 'better_versions' not in data
            self.better_versions = set([data['better_version']])

        for rel in self.relations:
            if rel in data:
                related = data[rel]

                if isinstance(related, (str, dict)):
                    related = [related]
                else:
                    assert isinstance(related, list)

                for x in related:
                    pr = PackageRelation(x)
                    # Fedora doesn't handle alternatives, everything must
                    # be handled with virtual packages. Assume the same is
                    # true for everything except dpkg.
                    assert not pr.alternatives, pr

                    if pr.contextual:
                        for context, specific in pr.contextual.items():
                            assert (context == 'deb' or
                                    not specific.alternatives), pr

                    if pr.package == 'libjpeg.so.62':
                        # we can't really translate versions for libjpeg,
                        # since it could be either libjpeg6b or libjpeg-turbo
                        assert pr.version is None

                    self.relations[rel].append(pr)

        for port in ('debian', 'rpm', 'arch', 'fedora', 'mageia', 'suse'):
            assert port not in data, 'use {deb: foo-dfsg, generic: foo} syntax'

        assert self.component in ('main', 'contrib', 'non-free', 'local'), self
        assert self.component == 'local' or 'license' in data, self
        assert self.section in ('games', 'doc', 'fonts'), 'unsupported'
        assert type(self.langs) is list
        assert type(self.mutually_exclusive) is bool

        for rel, related in self.relations.items():
            for pr in related:
                packages = set()
                if pr.contextual:
                    for p in pr.contextual.values():
                        packages.add(p.package)
                elif pr.alternatives:
                    for p in pr.alternatives:
                        packages.add(p.package)
                else:
                    packages.add(pr.package)
                assert self.name not in packages, \
                    "%s should not be in its own %s set" % (self.name, rel)

        if isinstance(self.install_to, dict):
            self.install_to.setdefault('generic', self.default_install_to)

        if 'install_to' in data and isinstance(data['install_to'], str):
            assert data['install_to'] != self.default_install_to, \
                "install_to for %s is extraneous" % self.name

        if 'demo_for' in data:
            if self.disks is None:
                self.disks = 1
            if type(data['demo_for']) is str:
                self.demo_for.add(data['demo_for'])
            else:
                self.demo_for |= set(data['demo_for'])
            assert self.name != data['demo_for'], \
                "a game can't be a demo for itself"

        if self.mutually_exclusive:
            assert (
                self.demo_for
                or self.better_versions
                or self.relations['provides']
            )

        if 'expansion_for' in data:
            if self.disks is None:
                self.disks = 1
            assert self.name != data['expansion_for'], \
                   "a game can't be an expansion for itself"
            if 'demo_for' in data:
                raise AssertionError(
                    "%r can't be both a demo of %r and an expansion for %r"
                    % (self.name, self.demo_for, self.expansion_for)
                )

        if 'install' in data:
            for filename in data['install']:
                self.install.add(filename)

        if 'optional' in data:
            assert isinstance(data['optional'], list), self.name
            for filename in data['optional']:
                self.optional.add(filename)

        if 'activated_by' in data:
            assert isinstance(data['activated_by'], list), self.name
            for filename in data['activated_by']:
                self.activated_by.add(filename)

        if 'doc' in data:
            assert isinstance(data['doc'], list), self.name
            for filename in data['doc']:
                self.optional.add(filename)

        if 'license' in data:
            assert isinstance(data['license'], list), self.name
            for filename in data['license']:
                self.optional.add(filename)

        if 'version' in data:
            self.version = data['version'] + '+' + GAME_PACKAGE_VERSION

        if 'rip_cd' in data:
            assert isinstance(self.rip_cd.get('first_track', 2), int), \
                self.name
            assert isinstance(self.rip_cd.get('last_track', 99), int), \
                self.name
            assert isinstance(self.rip_cd['filename_format'], str), self.name
            self.rip_cd['filename_format'] % 1
            # we only support Ogg Vorbis & MP3 for now
            assert self.rip_cd['encoding'] in ['vorbis', 'mp3'], self.name

            if self.name.endswith('-music'):
                self.data_type = 'music'

            if self.name.endswith('-music') and self.description is None:
                self.description = "This package contains the soundtrack, " \
                                   "copied from the CD-ROM\n"
                if self.rip_cd['encoding'] == 'vorbis':
                    self.description += "and encoded in Ogg Vorbis."
                else:
                    self.description += "and encoded in MP3."

            if 'known_rips' in self.rip_cd:
                assert 'last_track' in self.rip_cd, self.name

                for rip in self.rip_cd['known_rips']:
                    assert 'filename_format' in rip, self.name
                    rip['filename_format'] % 1
                    assert isinstance(rip.get('offset', 0), int), self.name

            if 'reuse' in self.rip_cd:
                assert 'last_track' in self.rip_cd, self.name
                assert 'package' in self.rip_cd['reuse'], self.name
                assert 'tracks' in self.rip_cd['reuse'], self.name

                # Make the keys of tracks be integers, which doesn't seem
                # to work well in YAML
                tracks = {}
                for k, v in self.rip_cd['reuse']['tracks'].items():
                    assert isinstance(v, int)
                    tracks[int(k)] = v
                self.rip_cd['reuse']['tracks'] = tracks

            if 'alternatives' in self.rip_cd:
                for altname, fileset in self.rip_cd['alternatives'].items():
                    assert isinstance(altname, str), self.name
                    assert isinstance(fileset, list), self.name

            if 'symlinks' in self.rip_cd:
                for symlink in self.rip_cd['symlinks']:
                    assert 'filename_format' in symlink, self.name
                    assert 'offset' in symlink, self.name
                    symlink['filename_format'] % 1
                    assert isinstance(symlink.get('offset'), int), self.name

        elif self.section == 'doc':
            self.data_type = 'documentation'

    def __repr__(self) -> str:
        return '<%s %r>' % (self.__class__.__name__, self.name)

    @property
    def aliases(self) -> set[str]:
        return self._aliases

    @aliases.setter
    def aliases(
        self,
        value: Iterable[str],
    ) -> None:
        self._aliases = set(value)

    @property
    def lintian_overrides(self) -> set[str]:
        return self._lintian_overrides

    @lintian_overrides.setter
    def lintian_overrides(
        self,
        value: Iterable[str],
    ) -> None:
        self._lintian_overrides = set(value)

    @property
    def install(self) -> set[str]:
        return self._install

    @install.setter
    def install(
        self,
        value: Iterable[str],
    ) -> None:
        self._install = set(value)

    @property
    def only_file(self) -> str | None:
        if len(self._install) == 1:
            return list(self._install)[0]
        else:
            return None

    @property
    def optional(self) -> set[str]:
        return self._optional

    @optional.setter
    def optional(
        self,
        value: Iterable[str],
    ) -> None:
        self._optional = set(value)

    @property
    def better_versions(self) -> set[str]:
        return self._better_versions

    @better_versions.setter
    def better_versions(
        self,
        value: Iterable[str],
    ) -> None:
        self._better_versions = set(value)

    @property
    def type(self) -> str:
        """type of package: full, demo, expansion or doc

        full packages include quake-registered, quake2-full-data, quake3-data
        demo packages include quake-shareware, quake2-demo-data
        expansion packages include quake-armagon, quake-music, quake2-rogue
        doc packages include larry-doc
        """
        if self.demo_for:
            return 'demo'

        if self.expansion_for or self.expansion_for_ext:
            return 'expansion'

        if self.section == 'doc':
            return 'doc'

        return 'full'

    @property
    def lang(self) -> str:
        return self.langs[0]

    @lang.setter
    def lang(self, value: str) -> None:
        assert type(value) is str
        self.langs = [value]

    def to_data(
        self,
        expand: bool = True,
        files: dict[str, WantedFile] | None = None,
        groups: dict[str, FileGroup] | None = None,
    ) -> dict[str, Any]:
        ret: dict[str, Any] = {}

        if expand:
            ret['name'] = self.name
            ret['type'] = self.type

        if expand or self.architecture != 'all':
            ret['architecture'] = self.architecture

        if expand or self.component != 'local':
            ret['component'] = self.component

        if expand or self.install_to != self.default_install_to:
            ret['install_to'] = self.install_to

        if expand or self.section != 'games':
            ret['section'] = self.section

        if expand or self.version != GAME_PACKAGE_VERSION:
            version = self.version

            if version.endswith('+' + GAME_PACKAGE_VERSION):
                version = version[:-(len(GAME_PACKAGE_VERSION) + 1)]

            ret['version'] = version

        for k in (
                'aliases',
                'better_versions',
                'demo_for',
                'empty',
                'gog',
                'lintian_overrides',
                'mutually_exclusive',
                'origin',
                'rip_cd',
                'steam',
                'symlinks',
                ):
            v = getattr(self, k)
            if v:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        for relation, related in self.relations.items():
            # The .to_data() of a PackageRelation doesn't have a defined
            # sorting order, so do a Schwartzian transform to get a
            # stable order
            tmp = sorted([(str(x), x.to_data()) for x in related])
            if tmp:
                tmp2 = [x[1] for x in tmp]
                ret[relation] = tmp2

        if expand and self.install_files is not None:
            if self.install_files:
                ret['install'] = sorted(f.name for f in self.install_files)

            if self.activated_by_files:
                ret['activated_by'] = sorted(
                    f.name for f in self.activated_by_files)
        else:
            if self.install:
                ret['install'] = sorted(self.install)

            if self.activated_by:
                ret['activated_by'] = sorted(self.activated_by)

        if self.optional:
            optional = set()
            licenses = set()
            docs = set()

            if expand and self.optional_files is not None:
                for of in self.optional_files:
                    if of.license:
                        licenses.add(of.name)

                    if of.doc:
                        docs.add(of.name)

                    if not of.doc and not of.license:
                        optional.add(of.name)

            elif files is not None and groups is not None:
                f: WantedFile | FileGroup | None
                for name in self.optional:
                    if name in groups:
                        f = groups[name]
                    elif name in files:
                        f = files[name]
                    else:
                        # can't distinguish
                        f = None

                    if f is not None and f.license:
                        licenses.add(f.name)

                    if f is not None and f.doc:
                        docs.add(f.name)

                    if f is None or not (f.doc or f.license):
                        optional.add(name)

            else:
                # can't distinguish between docs, licenses and others
                optional = self.optional

            if optional:
                ret['optional'] = sorted(optional)

            if licenses:
                ret['license'] = sorted(licenses)

            if docs:
                ret['doc'] = sorted(docs)

        if expand or self.langs != ['en']:
            ret['langs'] = self.langs

        for k in (
                'copyright',
                'disks',
                'engine',
                'expansion_for',
                'expansion_for_ext',
                'longname',
                'multi_arch',
                'short_description',
                'url_misc',
                'wiki',
                ):
            v = getattr(self, k)
            if v is not None:
                ret[k] = v

        for k in (
                'copyright_notice',
                'description',
                'long_description',
                ):
            v = getattr(self, k)
            if v is not None:
                ret[k] = YamlLiteral(v)

        # TODO: data_type should also be here, but its default is
        # complicated

        return ret
