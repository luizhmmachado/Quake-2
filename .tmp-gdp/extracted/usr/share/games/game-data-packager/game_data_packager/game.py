#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import argparse
import glob
import importlib
import io
import json
import logging
import os
import random
import re
import sys
import zipfile
from collections.abc import Iterator
from typing import (Any, TextIO, TYPE_CHECKING, cast, overload)

from .build import (PackagingTask)
from .data import (FileGroup, Package, WantedFile, YamlLiteral)
from .packaging import (Compression, NoPackaging, PackagingTaskArgs)
from .paths import (DATADIR)
from .util import (ascii_safe, load_yaml)
from .version import (GAME_PACKAGE_VERSION)

if TYPE_CHECKING:
    from typing import Unpack

logger = logging.getLogger(__name__)

MD5SUM_DIVIDER = re.compile(r' [ *]?')

MULTI_CD_DISCLAIMER = '''\
for multi-cd games, you'll first need to ensure that all the data
is accessible simultaneously, e.g. copy data from CD1 to CD3 in /tmp/cd{1-3}
and let CD4 *mounted* in the drive.

It's important to first mkdir '/tmp/cd1 /tmp/cd2 /tmp/cd3' because for some
games there are different files across the disks with the same name that
would be overwriten.

If /tmp/ is on a tmpfs and you don't have something like 16GB of RAM,
you'll likely need to store the files somewhere else.

The game can then be packaged this way:
$ game-data-packager {game} /tmp/cd1 /tmp/cd2 /tmp/cd3 /media/cdrom0
'''


class GameData:
    def __init__(
        self,
        shortname: str,
        data: dict[str, Any],
    ) -> None:
        # The name of the game for command-line purposes, e.g. quake3
        self.shortname = shortname

        # Other command-line names for this game
        self.aliases: set[str] = set()

        # The formal name of the game, e.g. Quake III Arena
        self.longname: str = shortname.title()

        # Engine's wiki base URL, provided by engine plugin
        self.wikibase: str = ''
        # Game page on engine's wiki
        self.wiki: str | None = None

        # Wikipedia page, linked from per-engine wikis
        self.wikipedia: str | None = None

        # The franchise this game belongs to.
        # this is used to loosely ties various .yaml files
        self.franchise: str | None = None

        # The one-line copyright notice used to build debian/copyright
        self.copyright: str | None = None

        # A blurb of text that is used to build debian/copyright
        self.copyright_notice: str | None = None

        # Tag fanmade games so they don't screw up year * size regression
        self.fanmade: bool = False

        # The game engine used to run the game (package name)
        self.engine: None | str | dict[str, str] = None

        # Game translations known to exists, but missing in 'packages:'
        # list of ISO-639 codes
        self.missing_langs: list[str] = []

        # The game genre, as seen in existing .desktop files or
        # https://en.wikipedia.org/wiki/List_of_video_game_genres
        self.genre: str | None = None

        # binary package name => Package
        self.packages: dict[str, Package] = {}

        # Subset of packages.values() with nonempty rip_cd
        self.rip_cd_packages: set[Package] = set()

        # Number of CD the full game was sold on
        self.disks: int | None = None

        self.help_text: str = ''

        # Extra directories where we might find game files
        self.try_repack_from: list[str] = []

        # If non-empty, the game requires binary executables which are only
        # available for the given architectures (typically i386)
        self.binary_executables: str = ''

        # online stores metadata
        self.steam: dict[str, Any] = {}
        self.gog: dict[str, Any] = {}
        self.origin: dict[str, Any] = {}

        # full url of online game shops
        self.url_steam: str | None = None
        self.url_gog: str | None = None
        self.url_misc: str | None = None

        self.data = data

        self.argument_parser = None

        # How to compress the .deb:
        # True: dpkg-deb's default
        # False: -Znone
        # str: -Zstr (gzip, xz or none)
        # list: arbitrary options (e.g. -z9 -Zgz -Sfixed)
        self.compression: Compression = True

        # YAML filename to use, overriding normal search path
        self.yaml_file: str | None = None

        for k in (
            'binary_executables',
            'compression',
            'copyright',
            'copyright_notice',
            'disks',
            'engine',
            'fanmade',
            'franchise',
            'genre',
            'gog',
            'help_text',
            'longname',
            'missing_langs',
            'origin',
            'steam',
            'url_misc',
            'wiki',
            'wikibase',
            'wikipedia',
        ):
            if k in self.data:
                setattr(self, k, self.data[k])

        if isinstance(self.engine, dict) and 'generic' not in self.engine:
            self.engine['generic'] = None

        assert type(self.missing_langs) is list

        if 'aliases' in self.data:
            self.aliases = set(self.data['aliases'])

        if 'try_repack_from' in self.data:
            paths = self.data['try_repack_from']
            if isinstance(paths, list):
                self.try_repack_from = paths
            elif isinstance(paths, str):
                self.try_repack_from = [paths]
            else:
                raise AssertionError('try_repack_from should be str or list')

        # True if the lazy load of full file info has been done
        self.loaded_file_data = False

        # Map from WantedFile name to instance.
        # { 'baseq3/pak1.pk3': WantedFile instance }
        self.files: dict[str, WantedFile] = {}

        # Map from FileGroup name to instance.
        self.groups: dict[str, FileGroup] = {}

        # Map from WantedFile name to a set of names of WantedFile instances
        # from which the file named in the key can be extracted or generated.
        # { 'baseq3/pak1.pk3': set(['linuxq3apoint-1.32b-3.x86.run']) }
        self.providers: dict[str, set[str]] = {}

        # Map from WantedFile look_for name to a set of names of WantedFile
        # instances which might be it
        # { 'doom2.wad': set(['doom2.wad_1.9', 'doom2.wad_bfg', ...]) }
        self.known_filenames: dict[str, set[str]] = {}

        # Map from WantedFile size to a set of names of WantedFile
        # instances which might be it
        # { 14604584: set(['doom2.wad_1.9']) }
        self.known_sizes: dict[int, set[str]] = {}

        # Maps from md5, sha1, sha256 to a set of names of WantedFile instances
        # { '25e1459...': set(['doom2.wad_1.9']) }
        self.known_md5s: dict[str, set[str]] = {}
        self.known_sha1s: dict[str, set[str]] = {}
        self.known_sha256s: dict[str, set[str]] = {}

        self._populate_files(self.data.get('files'))

        assert 'packages' in self.data

        for binary, data in self.data['packages'].items():
            # these should only be at top level, since they are global
            assert 'sha1sums' not in data, binary
            assert 'sha256sums' not in data, binary

            if 'DISABLED' in data:
                continue
            package = self.construct_package(binary, data)
            self.packages[binary] = package
            self._populate_package(package, data)

        if 'groups' in self.data:
            groups = self.data['groups']
            assert isinstance(groups, dict), self.shortname

            # Before doing anything else, we do one pass through the list
            # of groups to record that each one is a group, so that when we
            # encounter an entry that is not known to be a group in a
            # group's members, it is definitely a file.
            for group_name in groups:
                self.ensure_group(group_name)

            for group_name, group_data in groups.items():
                group = self.groups[group_name]
                attrs = {}

                if isinstance(group_data, dict):
                    members = group_data['group_members']
                    for k, v in group_data.items():
                        if k != 'group_members':
                            assert hasattr(group, k), k
                            setattr(group, k, v)
                            attrs[k] = v
                elif isinstance(group_data, (str, list)):
                    members = group_data
                else:
                    raise AssertionError(
                        'group %r should be dict, str or list' % group_name,
                    )

                if isinstance(members, str):
                    for line in members.splitlines():
                        f = self._add_hash(line.rstrip('\n'), 'size_and_md5')
                        if f is not None:
                            # f may be a WantedFile or a FileGroup,
                            # this works for either
                            group.group_members.add(f.name)
                            group.apply_group_attributes(f)

                elif isinstance(members, list):
                    for member_name in members:
                        f = self.groups.get(member_name)

                        if f is None:
                            f = self._ensure_file(member_name)

                        # f may be a WantedFile or a FileGroup,
                        # this works for either
                        group.group_members.add(f.name)
                        group.apply_group_attributes(f)
                else:
                    raise AssertionError(
                        'group %r members should be str or list' % group_name,
                    )

        if 'size_and_md5' in self.data:
            for line in self.data['size_and_md5'].splitlines():
                self._add_hash(line, 'size_and_md5')

        for alg in ('sha1', 'sha256'):
            if alg + 'sums' in self.data:
                for line in self.data[alg + 'sums'].splitlines():
                    self._add_hash(line, alg)

        # compute webshop URL's
        gog_url = self.gog.get('url')
        gog_removed = self.gog.get('removed')
        gog_pp = '22d200f8670dbdb3e253a90eee5098477c95c23d'     # ScummVM
        steam_id = self.steam.get('id')
        for p in sorted(self.packages.keys(), reverse=True):
            package = self.packages[p]
            if package.gog:
                gog_url = package.gog.get('url', gog_url)
                gog_removed = package.gog.get('removed', gog_removed)
                gog_pp = package.gog.get('pp', gog_pp)
            p_steam_id = package.steam.get('id')
            if p_steam_id and (steam_id is None or p_steam_id < steam_id):
                steam_id = p_steam_id
            if package.url_misc:
                self.url_misc = package.url_misc
        if steam_id:
            self.url_steam = (
                'http://store.steampowered.com/app/%s/' % steam_id
            )
        if gog_url and not gog_removed:
            self.url_gog = (
                'https://www.gog.com/game/' + gog_url + '?pp=' + gog_pp
            )

    def __repr__(self) -> str:
        return '<%s.%s %r>' % (
            __name__,
            self.__class__.__name__,
            self.shortname,
        )

    def edit_help_text(self) -> str:
        help_text = ''

        class HelpEntry:
            year: int = 1970

            def __init__(
                self,
                game_type: int,
                copyright: str | None,
                name: str,
                longname: str
            ) -> None:
                self.game_type = game_type
                if copyright:
                    self.year = int(copyright.split()[1][0:4])
                self.name = name
                self.longname = longname

        if len(self.packages) > 1 or self.disks:
            help_text = '\npackages possible for this game:\n'
            help = []
            has_multi_cd = False
            for package in self.packages.values():
                disks = package.disks or self.disks or 1
                longname = package.longname or self.longname
                if disks > 1:
                    has_multi_cd = True
                    longname += ' (%dCD)' % disks
                game_type = {
                    'demo': 1,
                    'full': 2,
                    'expansion': 3,
                }.get(package.type, 4)
                help.append(HelpEntry(game_type,
                                      package.copyright or self.copyright,
                                      package.name,
                                      longname))
            for h in sorted(
                help, key=lambda k: (k.game_type, k.year, k.name),
            ):
                help_text += "  %-40s %s\n" % (h.name, h.longname)
            if has_multi_cd and self.shortname != 'zork-inquisitor':
                help_text += "\nWARNING: "
                for line in MULTI_CD_DISCLAIMER:
                    help_text += '\n         '.join(line)

        if self.help_text:
            help_text += '\n' + self.help_text

        if self.missing_langs:
            help_text += ('\nThe following languages are not '
                          'yet supported: %s\n' %
                          ','.join(self.missing_langs))

        # advertise where to buy games
        # if it's not already in the help_text
        www = list()
        if (
            self.url_steam
            and '://store.steampowered.com/' not in self.help_text
        ):
            www.append(self.url_steam)
        if self.url_gog and '://www.gog.com/' not in self.help_text:
            www.append(self.url_gog)
        if self.url_misc:
            www.append(self.url_misc)
        if www:
            random.shuffle(www)
            help_text += '\nThis game can be bought online here:\n  '
            help_text += '\n  '.join(www)

        wikis = list()
        if self.wiki:
            wikis.append(self.wikibase + self.wiki)
        for p in sorted(self.packages.keys()):
            package = self.packages[p]
            if package.wiki:
                wikis.append(self.wikibase + package.wiki)
        if self.wikipedia:
            wikis.append(self.wikipedia)
        if wikis:
            help_text += '\nExternal links:\n  '
            help_text += '\n  '.join(wikis)

        return help_text

    def to_data(
        self,
        expand: bool = True,
        include_ignorable: bool = False
    ) -> dict[str, str]:
        files: dict[str, Any] = {}
        groups: dict[str, Any] = {}
        packages: dict[str, Any] = {}
        ret: dict[str, Any] = {}

        def sort_set_values(
            d: dict[str, set[str]]
        ) -> dict[str, list[str]]:
            ret = {}
            for k, v in d.items():
                assert isinstance(v, set), (repr(k), repr(v))
                ret[k] = sorted(v)
            return ret

        for filename, f in self.files.items():
            if f.ignorable and not include_ignorable:
                continue

            data = f.to_data(expand=expand)

            for g in self.groups.values():
                if filename in g.group_members:
                    for attr in FileGroup.RECURSIVELY_APPLIED:
                        if getattr(g, attr) == data.get(attr):
                            data.pop(attr, None)

            if data or expand:
                files[filename] = data

        for name, g in self.groups.items():
            if g.ignorable and not include_ignorable:
                continue

            if not g.group_members:
                continue

            groups[name] = g.to_data(
                expand=expand, files=self.files,
                include_ignorable=include_ignorable)

        for name, package in self.packages.items():
            packages[name] = package.to_data(
                expand=expand, files=self.files, groups=self.groups)

        if files:
            ret['files'] = files

        if groups:
            ret['groups'] = groups

        ret['packages'] = packages

        if expand:
            for k in (
                    'known_filenames',
                    'known_md5s',
                    'known_sha1s',
                    'known_sha256s',
                    'known_sizes',
                    'providers',
                    ):
                v = getattr(self, k)
                if v:
                    ret[k] = sort_set_values(v)

            if self.rip_cd_packages:
                names = [p.name for p in self.rip_cd_packages]
                ret['rip_cd_packages'] = sorted(names)

        unknown_md5s = set()
        unknown_sha1s = set()
        unknown_sha256s = set()

        for filename, f in self.files.items():
            if f.alternatives:
                continue

            if f.ignorable and not include_ignorable:
                continue

            if f.md5 is None:
                unknown_md5s.add(filename)

            if f.sha1 is None:
                unknown_sha1s.add(filename)

            if f.sha256 is None:
                unknown_sha256s.add(filename)

        if unknown_md5s:
            ret['unknown_md5s'] = sorted(unknown_md5s)

        if unknown_sha1s:
            ret['unknown_sha1s'] = sorted(unknown_sha1s)

        if unknown_sha256s:
            ret['unknown_sha256s'] = sorted(unknown_sha256s)

        for k in (
                'copyright',
                ):
            v = getattr(self, k)
            if v is not None:
                ret[k] = v

        for k in (
                'try_repack_from',
                ):
            v = getattr(self, k)
            if v:
                ret[k] = v

        for k in (
                'copyright_notice',
                'help_text',
                ):
            v = getattr(self, k)
            if v:
                ret[k] = YamlLiteral(v)

        if expand or self.longname != self.shortname.title():
            ret['longname'] = self.longname

        sha1s = []
        sha256s = []
        ungrouped = []
        unknown_sizes = []

        for filename in sorted(self.files.keys()):
            f = self.files[filename]
            prefix = ''

            if f.ignorable:
                if not include_ignorable:
                    continue

                prefix = '.'

            if f.sha1 is not None:
                sha1s.append('%s%-40s %s\n' % (prefix, f.sha1, f.name))

            if f.sha256 is not None:
                sha256s.append('%s%-64s %s\n' % (prefix, f.sha256, f.name))

            if f.size is None and not f.ignorable:
                unknown_sizes.append(filename)

            for g in self.groups.values():
                if filename in g.group_members:
                    break
            else:
                size: Any = f.size
                md5: Any = f.md5

                if size is None:
                    size = '_'

                if md5 is None:
                    md5 = '_'

                ungrouped.append(
                    '%s%-9s %32s %s\n' % (prefix, size, md5, filename))

        if unknown_sizes:
            ret['unknown_sizes'] = unknown_sizes

        if ungrouped:
            ret['size_and_md5'] = YamlLiteral(''.join(ungrouped))

        if sha1s:
            ret['sha1sums'] = YamlLiteral(''.join(sha1s))

        if sha256s:
            ret['sha256sums'] = YamlLiteral(''.join(sha256s))

        return ret

    def size(self, package: Package) -> tuple[int, int]:
        assert package.install_files is not None, \
            'should have loaded file data before calling size()'
        assert package.optional_files is not None, \
            'should have loaded file data before calling size()'
        size_min = 0
        size_max = 0
        for file in package.install_files:
            if file.alternatives:
                # 'or 0' is a workaround for the files without known size
                size_min += min(
                    set(self.files[a].size or 0 for a in file.alternatives)
                )
                size_max += max(
                    set(self.files[a].size or 0 for a in file.alternatives)
                )
            elif file.size:
                size_min += file.size
                size_max += file.size
        for file in package.optional_files:
            if file.alternatives:
                size_max += max(
                    set(self.files[a].size or 0 for a in file.alternatives)
                )
            elif file.size:
                size_max += file.size
        return (size_min, size_max)

    def _populate_package(
        self,
        package: Package,
        d: dict[str, Any]
    ) -> None:
        if isinstance(package.engine, dict):
            if isinstance(self.engine, dict):
                for k in self.engine:
                    package.engine.setdefault(k, self.engine[k])
            else:
                package.engine.setdefault('generic', self.engine)

        assert self.copyright or package.copyright, package.name

        if 'demo_for' in d:
            if not package.longname:
                if package.lang != 'en':
                    package.longname = (
                        self.longname + ' (demo %s)' % package.lang
                    )
                else:
                    package.longname = self.longname + ' (demo)'
        else:
            assert 'demo' not in package.name or len(self.packages) == 1, \
                package.name + ' miss a demo_for tag.'
            if not package.longname and package.lang != 'en':
                package.longname = self.longname + ' (%s)' % package.lang

        if package.mutually_exclusive:
            assert (
                package.demo_for
                or package.better_versions
                or package.relations['provides']
            )

    def _populate_files(
        self,
        d: dict[str, Any] | None,
        **kwargs: Any
    ) -> None:
        if d is None:
            return

        for filename, data in d.items():
            f = self._ensure_file(filename)

            for k in kwargs:
                setattr(f, k, kwargs[k])

            assert 'optional' not in data, filename
            if 'look_for' in data and 'install_as' in data:
                assert data['look_for'] != [data['install_as']], filename
            for k in (
                    'alternatives',
                    'distinctive_name',
                    'distinctive_size',
                    'doc',
                    'download',
                    'executable',
                    'install_as',
                    'install_to',
                    'license',
                    'look_for',
                    'md5',
                    'provides',
                    'sha1',
                    'sha256',
                    'size',
                    'skip_hash_matching',
                    'unpack',
                    'unsuitable',
                    ):
                if k in data:
                    setattr(f, k, data[k])

    def ensure_group(self, name: str) -> FileGroup:
        assert name not in self.files, (self.shortname, name)

        if name not in self.groups:
            logger.debug('Adding group: %s', name)
            self.groups[name] = FileGroup(name)

        return self.groups[name]

    def _ensure_file(self, name: str) -> WantedFile:
        assert name not in self.groups, (self.shortname, name)

        if name not in self.files:
            logger.debug('Adding file: %s', name)
            self.files[name] = WantedFile(name)

        return self.files[name]

    def add_parser(
        self,
        parsers: argparse._SubParsersAction[Any],
        base_parser: argparse.ArgumentParser,
        **kwargs: Any
    ) -> argparse.ArgumentParser:
        aliases = self.aliases

        longname = ascii_safe(self.longname)

        parser = parsers.add_parser(
            self.shortname,
            help=longname,
            aliases=sorted(aliases),
            description='Package data files for %s.' % longname,
            epilog=ascii_safe(self.edit_help_text()),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            parents=(base_parser,),
            **kwargs,
        )

        parser.add_argument(
            'paths', nargs='*',
            metavar='DIRECTORY|FILE',
            help='Files to use in constructing the .deb',
        )

        self.argument_parser = parser
        return cast(argparse.ArgumentParser, parser)

    def _add_hash(
        self,
        line: str,
        alg: str,
    ):  # -> HashedFile? | None:
        """Parse one line from md5sums-style data."""

        stripped = line.strip()
        ignorable = False

        if stripped == '' or stripped.startswith('#'):
            return None

        if stripped[0] == '.':
            ignorable = True
            stripped = stripped[1:]

        if alg == 'size_and_md5':
            size, hexdigest, filename = stripped.split(None, 2)
            alg = 'md5'
        else:
            size = None
            hexdigest, filename = MD5SUM_DIVIDER.split(stripped, 1)

        if filename in self.groups:
            assert size in (None, '_'), \
                "%s group %s should not have size" % (self.shortname, filename)
            assert hexdigest in (None, '_'), \
                "%s group %s should not have hexdigest" \
                % (self.shortname, filename)
            return self.groups[filename]

        f = self._ensure_file(filename)

        if size is not None and size != '_':
            f.size = int(size)

        if hexdigest is not None and hexdigest != '_':
            setattr(f, alg, hexdigest)

        if ignorable:
            f.ignorable = True

        return f

    def _populate_groups(self, stream: TextIO) -> None:
        current_group = None
        attributes: dict[str, Any] = {}

        for line in stream:
            stripped = line.strip()

            if stripped == '' or stripped.startswith('#'):
                continue

            # The group data starts with a list of groups. This is necessary
            # so we can know whether a group member, encountered later on in
            # the data, is a group or a file.
            if stripped.startswith('*'):
                assert current_group is None
                self.ensure_group(stripped[1:])
            # After that, [Group] opens a section for each group
            elif stripped.startswith('['):
                assert stripped.endswith(']'), repr(stripped)
                current_group = self.ensure_group(stripped[1:-1])
                attributes = {}
            # JSON metadata is on a line with {}
            elif stripped.startswith('{'):
                assert current_group is not None
                attributes = json.loads(stripped)
                assert type(attributes) is dict

                for k, v in attributes.items():
                    assert hasattr(current_group, k), k
                    setattr(current_group, k, v)
            # Every other line is a member, either a file or a group
            else:
                f = self._add_hash(stripped, 'size_and_md5')
                # f can either be a WantedFile or a FileGroup here
                assert current_group is not None
                current_group.apply_group_attributes(f)
                current_group.group_members.add(f.name)

    def load_file_data(
        self,
        check: bool = ('GDP_UNINSTALLED' in os.environ),
        datadir: str = DATADIR,
        use_vfs: bool | str = True,
    ) -> None:
        if self.loaded_file_data:
            return

        logger.debug('loading full data')

        if self.yaml_file is not None:
            data = load_yaml(open(self.yaml_file, encoding='utf-8'))

            for group_name, group_data in sorted(
                    data.get('groups', {}).items()):
                group = self.ensure_group(group_name)

                if isinstance(group_data, dict):
                    members = group_data['group_members']
                    for k, v in group_data.items():
                        if k != 'group_members':
                            setattr(group, k, v)
                elif isinstance(group_data, (str, list)):
                    members = group_data
                else:
                    raise AssertionError(
                        'group %r should be dict, str or list' % group_name)

                has_members = False

                if isinstance(members, str):
                    for line in members.splitlines():
                        line = line.strip()
                        if line and not line.startswith('#'):
                            has_members = True
                            f = self._add_hash(line, 'size_and_md5')
                            # f can either be a WantedFile or a FileGroup here
                            group.apply_group_attributes(f)
                            group.group_members.add(f.name)
                elif isinstance(members, list):
                    for m in members:
                        has_members = True
                        f = self._add_hash('? ? ' + m, 'size_and_md5')
                        # f can either be a WantedFile or a FileGroup here
                        group.apply_group_attributes(f)
                        group.group_members.add(f.name)
                else:
                    raise AssertionError(
                        'group %r members should be str or list' % group_name)

                # an empty group is no use, and would break the assumption
                # that we can use f.group_members to detect groups
                assert has_members

            for k in ('sha1sums', 'sha256sums', 'size_and_md5'):
                v = data.get(k, None)

                if k.endswith('sums'):
                    k = k[:-4]

                if v is not None:
                    for line in v.splitlines():
                        stripped = line.strip()

                        if stripped == '' or stripped.startswith('#'):
                            continue

                        self._add_hash(stripped, k)

        elif use_vfs:
            if isinstance(use_vfs, str):
                zip = use_vfs
            else:
                zip = os.path.join(DATADIR, 'vfs.zip')

            with zipfile.ZipFile(zip, 'r') as zf:
                files = zf.namelist()

                filename = '%s.groups' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    stream = io.TextIOWrapper(
                        zf.open(filename), encoding='utf-8',
                    )
                    self._populate_groups(stream)

                filename = '%s.files' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    jsondata = zf.open(filename).read().decode('utf-8')
                    data = json.loads(jsondata)
                    self._populate_files(data)

                for alg in ('sha1', 'sha256', 'size_and_md5'):
                    filename = '%s.%s%s' % (
                        self.shortname, alg,
                        '' if alg == 'size_and_md5' else 'sums',
                    )
                    if filename in files:
                        logger.debug('... %s/%s', zip, filename)
                        rawdata = zf.open(filename).read().decode('utf-8')
                        for line in rawdata.splitlines():
                            self._add_hash(line.rstrip('\n'), alg)
        else:
            vfs = os.path.join(DATADIR, 'data')

            if not os.path.isdir(vfs):
                vfs = DATADIR

            filename = os.path.join(vfs, '%s.groups' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                stream = open(filename, encoding='utf-8')
                self._populate_groups(stream)

            filename = os.path.join(vfs, '%s.files' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                data = json.load(open(filename, encoding='utf-8'))
                self._populate_files(data)

            for alg in ('sha1', 'sha256', 'size_and_md5'):
                filename = os.path.join(
                    vfs, '%s.%s%s' % (
                        self.shortname, alg,
                        '' if alg == 'size_and_md5' else 'sums'
                    )
                )
                if os.path.isfile(filename):
                    logger.debug('... %s', filename)
                    with open(filename) as f:
                        for line in f:
                            self._add_hash(line.rstrip('\n'), alg)

        self.loaded_file_data = True

        for package in self.packages.values():
            d = self.data['packages'][package.name]

            for f in self.iter_groups(d.get('doc', ())):
                f.doc = True

            for f in self.iter_expand_groups(d.get('doc', ())):
                f.doc = True

            for f in self.iter_groups(d.get('license', ())):
                f.license = True

            for f in self.iter_expand_groups(d.get('license', ())):
                f.license = True

            package.install_files = set(
                self.iter_expand_groups(package.install)
            )
            package.optional_files = set(
                self.iter_expand_groups(package.optional)
            )
            package.activated_by_files = set(
                self.iter_expand_groups(package.activated_by)
            )

        # iter_expand_groups could change the contents of self.files
        for filename, f in list(self.files.items()):
            f.provides_files = set(self.iter_expand_groups(f.provides))

        for filename, f in self.files.items():
            for provided in f.provides_files:
                if not provided.ignorable:
                    self.providers.setdefault(
                        provided.name, set()
                    ).add(filename)

            if f.alternatives or f.ignorable:
                continue

            if f.distinctive_size and f.size is not None:
                self.known_sizes.setdefault(f.size, set()).add(filename)

            for lf in f.look_for:
                self.known_filenames.setdefault(lf, set()).add(filename)

            if f.md5 is not None:
                self.known_md5s.setdefault(f.md5, set()).add(filename)

            if f.sha1 is not None:
                self.known_sha1s.setdefault(f.sha1, set()).add(filename)

            if f.sha256 is not None:
                self.known_sha256s.setdefault(f.sha256, set()).add(filename)

        for package in self.packages.values():
            if package.rip_cd:
                if 'reuse' in package.rip_cd:
                    assert package.rip_cd['reuse']['package'] in self.packages

                self.rip_cd_packages.add(package)

        if not check:
            return

        # check for different files that shares same md5 & look_for
        for file in self.known_md5s:
            if len(self.known_md5s[file]) == 1:
                continue
            all_lf: set[str] = set()
            for f in self.known_md5s[file]:
                assert not all_lf.intersection(self.files[f].look_for), (
                   'duplicate file description in %s: %s'
                   % (self.shortname, ', '.join(self.known_md5s[file]))
                )
                all_lf |= self.files[f].look_for

        # consistency check
        packages_might_install = {}
        package_excludes = {}

        for package in self.packages.values():
            # there had better be something it wants to install, unless
            # specifically marked as empty
            if package.empty:
                assert not package.install_files, package.name
                assert not package.rip_cd, package.name
            else:
                assert package.install_files or package.rip_cd, \
                    package.name

            # check internal depedencies
            for demo_for_item in package.demo_for:
                assert demo_for_item in self.packages, demo_for_item

            if package.expansion_for:
                if package.expansion_for not in self.packages:
                    # It needs to be provided on all distributions,
                    # so we can ignore contextual package relations,
                    # which have package = None.
                    #
                    # We also already asserted that distro-independent
                    # relations don't have alternatives (not that they
                    # would be meaningful for provides).
                    provider = None

                    for other in self.packages.values():
                        for provided in other.relations['provides']:
                            if package.expansion_for == provided.package:
                                provider = other
                                break

                        if provider is not None:
                            break
                    else:
                        raise Exception(
                            '%s: %s: virtual package %s not found'
                            % (
                                self.shortname,
                                package.name,
                                package.expansion_for,
                            )
                        )

            if package.better_versions:
                for v in package.better_versions:
                    assert v in self.packages, v

            # check for stale missing_langs
            if not package.demo_for:
                assert not set(package.langs).intersection(self.missing_langs)

            # check for missing 'version:'
            assert package.install_files is not None, \
                'should have loaded file data by the time we get here'
            for wanted in package.install_files:
                if self.files[wanted.name].filename == 'version':
                    assert package.version != GAME_PACKAGE_VERSION, \
                        package.name

            might_install: dict[str, WantedFile] = {}
            packages_might_install[package.name] = might_install

            no_packaging = NoPackaging()
            supported_archs = package.architecture.split()

            assert package.install_files is not None, \
                'should have loaded file data by the time we get here'
            assert package.optional_files is not None, \
                'should have loaded file data by the time we get here'
            for wanted in (package.install_files | package.optional_files):
                if (
                    wanted.architecture != 'all'
                    and package.architecture != 'any'
                    and wanted.architecture not in supported_archs
                ):
                    raise AssertionError(
                        'Cannot include Architecture: {} file "{}" in '
                        'Architecture: {} package "{}"'.format(
                            wanted.architecture, wanted.name,
                            ','.join(supported_archs), package.name,
                        )
                    )

                install_as = wanted.install_as
                install_to = no_packaging.substitute(
                    package.install_to, package.name,
                )

                if wanted.alternatives and install_as == '$alternative':
                    batch = [self.files[alt] for alt in wanted.alternatives]
                else:
                    batch = [wanted]

                # Do not add them to might_install immediately so that
                # alternatives with install_as = '$alternative' are allowed to
                # collide with each other (perhaps we have alternatives
                # foo.dat?1.0, foo.dat?2.0 and foo_censored.dat - that's fine
                # if we are never going to install both copies of foo.dat
                # together)
                batch_might_install = {}

                for installable in batch:
                    if installable.install_to is not None:
                        install_to = no_packaging.substitute(
                                installable.install_to, package.name,
                                install_to=install_to)

                    if install_as == '$alternative':
                        install_to = os.path.join(
                            install_to.strip('/'), installable.install_as,
                        )
                    else:
                        install_to = os.path.join(
                            install_to.strip('/'), install_as,
                        )

                    if install_to in might_install:
                        raise AssertionError(
                                'Package {} tries to install both {} and '
                                '{} as {}'.format(
                                    package.name, installable.name,
                                    might_install[install_to].name,
                                    install_to))

                    batch_might_install[install_to] = installable

                might_install.update(batch_might_install)

            excludes = set()

            for rel in package.relations['conflicts']:
                excludes.add(rel.package)

            for rel in package.relations['replaces']:
                excludes.add(rel.package)

            if package.mutually_exclusive:
                for name in package.demo_for:
                    excludes.add(name)

                for name in package.better_versions:
                    excludes.add(name)

                for rel in package.relations['provides']:
                    excludes.add(rel.package)

            package_excludes[package.name] = excludes

        for name, package in self.packages.items():
            might_install = packages_might_install[name]

            for other_name, other in self.packages.items():
                if package is other:
                    continue

                if other_name in package_excludes[name]:
                    continue

                if name in package_excludes[other_name]:
                    continue

                excluded = False

                for r in package.relations['provides']:
                    if r.package in package_excludes[other_name]:
                        excluded = True

                for r in other.relations['provides']:
                    if r.package in package_excludes[name]:
                        excluded = True

                if excluded:
                    continue

                other_might_install = packages_might_install[other_name]

                for m in might_install:
                    if m in other_might_install:
                        raise AssertionError(
                                'Package {} tries to install {} as {} '
                                'but {} tries to install {} there '
                                'and they are not mutually exclusive'.format(
                                    name, might_install[m].name, m,
                                    other_name, other_might_install[m].name))

        for filename, wanted in self.files.items():
            if wanted.provides:
                assert wanted.unpack is not None, filename

            if wanted.unpack:
                assert 'format' in wanted.unpack, filename
                assert wanted.provides_files, filename
                for f in wanted.provides_files:
                    assert f.alternatives == [], (filename, f.name)
                if wanted.unpack['format'] == 'cat':
                    assert len(wanted.provides) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'], list), \
                        filename
                    for other_part in wanted.unpack['other_parts']:
                        assert other_part in self.files, (filename, other_part)
                elif wanted.unpack['format'] in ('xdelta', 'xdelta3'):
                    assert len(wanted.provides) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'], list), \
                        filename
                    assert len(wanted.unpack['other_parts']) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'][0], str), \
                        filename
                    assert wanted.unpack['other_parts'][0] in self.files, \
                        filename

            if wanted.alternatives:
                for alt_name in wanted.alternatives:
                    alt = self.files[alt_name]
                    # an alternative can't be a placeholder for alternatives
                    assert not alt.alternatives, alt_name

                # if this is a placeholder for a bunch of alternatives, then
                # it doesn't make sense for it to have a defined checksum
                # or size
                assert wanted.md5 is None, wanted.name
                assert wanted.sha1 is None, wanted.name
                assert wanted.sha256 is None, wanted.name
                assert wanted.size is None, wanted.name
            elif not wanted.ignorable:
                assert (wanted.size is not None or filename in
                        self.data.get('unknown_sizes', ())
                        ), (self.shortname, wanted.name)

        for name, group in self.groups.items():
            for member_name in group.group_members:
                assert member_name in self.files or member_name in self.groups

    def iter_expand_groups(
        self,
        grouped: set[str],
    ) -> Iterator[WantedFile]:
        """Given a set of strings that are either filenames or groups,
        yield the WantedFile instances for those names or the members of
        those groups, recursively.
        """
        for filename in grouped:
            group = self.groups.get(filename)

            if group is not None:
                for x in self.iter_expand_groups(group.group_members):
                    yield x
            else:
                yield self._ensure_file(filename)

    def iter_groups(self, grouped: set[str]) -> Iterator[FileGroup]:
        for filename in grouped:
            group = self.groups.get(filename)

            if group is not None:
                yield group

                for x in self.iter_groups(group.group_members):
                    yield x

    def construct_task(
        self,
        **kwargs: Unpack[PackagingTaskArgs]
    ) -> PackagingTask:
        self.load_file_data()
        return PackagingTask(self, **kwargs)

    def construct_package(self, binary: str, data: dict[str, Any]) -> Package:
        return Package(binary, data)

    def gog_download_name(self, package: Package) -> str | None:
        if package.gog is False:
            return None
        gog = package.gog or self.gog
        if 'removed' in gog:
            return None
        return gog.get('game') or gog.get('url')


def load_games(
    game: str = '*',
    datadir: str = DATADIR,
    use_vfs: bool | str = True,
) -> dict[str, GameData]:
    progress = (
        game == '*' and sys.stderr.isatty()
        and not logger.isEnabledFor(logging.DEBUG)
    )
    games = {}

    for yamlfile in glob.glob(os.path.join(datadir, game + '.yaml')):
        if os.path.basename(yamlfile).startswith('launch-'):
            continue

        name = os.path.basename(yamlfile)
        assert name.endswith('.yaml'), yamlfile
        name = name[:-5]

        games[name] = load_game(progress, yamlfile, None, yaml_file=yamlfile)

    if use_vfs:
        if isinstance(use_vfs, str):
            zip = use_vfs
        else:
            zip = os.path.join(datadir, 'vfs.zip')

        with zipfile.ZipFile(zip, 'r') as zf:
            if game == '*':
                for entry in zf.infolist():
                    if entry.filename.endswith('.json'):
                        name = entry.filename[:-5]

                        if name in games:
                            # shadowed by a YAML file
                            continue

                        jsonfile = '%s/%s' % (zip, entry.filename)
                        jsondata = zf.open(entry).read().decode('utf-8')
                        games[name] = load_game(progress, jsonfile, jsondata)
            elif game in games:
                # shadowed by a YAML file
                pass
            else:
                jsonfile = game + '.json'
                jsondata = zf.open(jsonfile).read().decode('utf-8')
                games[game] = load_game(
                        progress, '%s/%s' % (zip, jsonfile), jsondata)
    else:
        vfs = os.path.join(DATADIR, 'data')

        if not os.path.isdir(vfs):
            vfs = DATADIR

        for jsonfile in glob.glob(os.path.join(vfs, game + '.json')):
            name = os.path.basename(jsonfile[:-5])

            if name in games:
                # shadowed by a YAML file
                continue

            jsondata = open(jsonfile, encoding='utf-8').read()
            games[name] = load_game(progress, jsonfile, jsondata)

    if progress:
        print(
            '\r%s\r' % (' ' * (len(games) // 4 + 1)),
            end='',
            flush=True,
            file=sys.stderr,
        )

    return games


__load_game_counter = 0


@overload
def load_game(
    progress: bool,
    filename: str,
    content: str,
    name: str | None = None,
    yaml_file: None = None,
) -> GameData:
    ...


@overload
def load_game(
    progress: bool,
    filename: str,
    content: None,
    *,
    name: str | None = None,
    yaml_file: str,
) -> GameData:
    ...


def load_game(
    progress: bool,
    filename: str,
    content: str | None,
    name: str | None = None,
    yaml_file: str | None = None,
) -> GameData:
    global __load_game_counter
    if progress:
        animation = ['.', '-', '*', '#']
        modulo = int(__load_game_counter) % len(animation)
        if modulo > 0:
            print('\b', end='', flush=True, file=sys.stderr)
        print(animation[modulo], end='', flush=True, file=sys.stderr)
        __load_game_counter += 1

    try:
        if name is None:
            name = os.path.basename(filename)
            name = name[:len(name) - 5]

        if yaml_file is not None:
            data = load_yaml(open(yaml_file, encoding='utf-8'))
        elif filename.endswith('.yaml'):
            assert content is not None, filename
            data = load_yaml(content)
        else:
            assert content is not None, filename
            data = json.loads(content)

        plugin = data.get('plugin', name)
        plugin = plugin.replace('-', '_')

        try:
            plugin = importlib.import_module(
                'game_data_packager.games.%s' % plugin,
            )
            game_data_constructor = plugin.GAME_DATA_SUBCLASS
        except ImportError as e:
            logger.debug('No special code for %s: %s', name, e)
            assert 'game_data_packager.games' in e.msg, e
            game_data_constructor = GameData
        except AttributeError as e:
            logger.debug('No special code for %s: %s', name, e)
            game_data_constructor = GameData

        game = game_data_constructor(name, data)
        assert isinstance(game, GameData)

        if yaml_file is not None:
            game.yaml_file = yaml_file

        return game
    except Exception:
        print('Error loading %s:\n' % filename)
        raise
