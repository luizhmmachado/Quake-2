#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import glob
import zipfile
from collections.abc import (Iterable, Iterator)
from shutil import which
from typing import (Any, BinaryIO, TYPE_CHECKING)

import yaml
try:
    from debian.deb822 import Deb822
    ON_DEBIAN = True
except ImportError:
    ON_DEBIAN = False

from .data import (HashedFile, PackageRelation, WantedFile)
from .game import (GameData, load_game, load_games)
from .gog import GOG
from .steam import parse_acf
from .unpack import (DpkgDebUnpacker, TarUnpacker)
from .unpack.auto import automatic_unpacker
from .unpack.innoextract import (InnoSetup)
from .util import (
        check_output,
        rm_rf,
        )

if TYPE_CHECKING:
    import argparse
    import io
    from .data import (FileGroup, Package)
    from .unpack import (StreamUnpackable)

logging.basicConfig()
logger = logging.getLogger(__name__)


def guess_lang(string: str) -> str | None:
    string = string.lower()
    path = os.path.basename(string.rstrip('/'))
    if path.split('-')[-1] in ('de', 'en', 'es', 'fr', 'it', 'ja', 'pl', 'ru'):
        return path
    for short, long in [('de', 'german'),
                        ('es', 'spanish'),
                        ('fr', 'french'),
                        ('it', 'italian'),
                        ('ja', 'japanese'),
                        ('pl', 'polish'),
                        ('ru', 'russian')]:
        if long in string:
            return short
    # check against other args
    for lang in (
        'german',
        'spanish',
        'french',
        'italian',
        'polish',
        'russian',
    ):
        for arg in sys.argv:
            if lang in arg:
                return 'en'
    return None


def is_probably_optional(file: str) -> bool:
    file = file.split('?')[0]
    name, ext = os.path.splitext(file.lower())
    if ext in ('cfg', 'cmd', 'com', 'drv', 'ico', 'ini'):
        return True
    return False


def is_license(file: str) -> bool:
    file = file.split('?')[0]
    name, ext = os.path.splitext(file.lower())
    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False
    for word in ('eula', 'license', 'vendor'):
        if word in name:
            return True
    return False


def iter_path_components(filename: str) -> Iterator[str]:
    dirname, basename = os.path.split(filename)

    if dirname == filename:
        # the root
        yield dirname
    elif dirname:
        for x in iter_path_components(dirname):
            yield x

    if basename:
        yield basename


def is_doc(file: str) -> bool:
    file = file.split('?')[0]

    for dirname in iter_path_components(file):
        if dirname.lower() in ('manual', 'docs', 'doc', 'help'):
            return True

    name, ext = os.path.splitext(file.lower())

    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False

    for word in ('changes', 'hintbook', 'manual', 'quickstart',
                 'readme', 'refcard', 'reference', 'support'):
        if word in name:
            return True

    return False


def is_dosbox(
    file: str,
    opened: BinaryIO | None = None
) -> bool:
    '''check if DOSBox assests are just dropped in games assets directory'''
    basename = os.path.basename(file)
    if basename in ('dosbox.conf',  'dosbox.exe',
                    'dosbox-0.71.tar.gz', 'dosbox-0.74.tar.gz',
                    'SDL_net.dll', 'SDL.dll', 'zmbv.dll', 'zmbv.inf'):
        return True
    # to check: COPYING.txt INSTALL.txt NEWS.txt THANKS.txt *.conf
    if basename.startswith('dosbox'):
        return True
    if basename not in ('AUTHORS.txt', 'README.txt'):
        return False

    txt: BinaryIO | io.BufferedReader
    if opened is None:
        txt = open(file, 'rb')
    else:
        txt = opened

    # We can't use a TextIOWrapper because tarfile's _Stream objects
    # don't implement seekable(), which breaks _FileInFile's
    # implementation of seekable().
    line = txt.readline()
    return 'dosbox' in line.decode('latin1').lower()


def is_runtime(path: str) -> bool:
    dir_l = path.lower()
    for runtime in ('data.now', 'directx', 'dosbox'):
        if '/%s/' % runtime in dir_l:
            return True
        if dir_l.endswith('/' + runtime):
            logger.warning('ignoring %s runtime at %s' % (runtime, path))
            return True
    return False


class Template:
    def __init__(
        self,
        game: GameData,
        strip_paths: Iterable[str] = ()
    ) -> None:
        self.game = game
        self.plugin: str | None = None
        self.strip_paths = strip_paths
        self.has_dosbox: bool = False
        self.preexisting_files = set(self.game.files.keys())

    def new_group(self, stem: str) -> FileGroup:
        i = 0
        name = stem

        while name in self.game.files or name in self.game.groups:
            i += 1
            name = '%s (%d)' % (stem, i)

        return self.game.ensure_group(name)

    def is_scummvm(self, path: str) -> bool:
        dir_l = path.lower()
        if dir_l.endswith('/scummvm') or '/scummvm/' in dir_l:
            self.plugin = 'scummvm_common'
            return True
        return False

    def add_archive(
        self,
        path: str,
        lower: bool = False,
        reader: Any = None,  # not used
        unpack: bool = True,
    ) -> WantedFile:
        out_name = os.path.basename(path)

        if lower:
            out_name = out_name.lower()

        result = self.add_file(path, out_name=out_name, unpack=unpack)
        self.game.ensure_group('archives').group_members.add(result.name)
        return result

    def add_unpacker(
        self,
        path: str,
        result: WantedFile,
        unpacker: StreamUnpackable
    ) -> None:
        if result.unpack is None:
            result.unpack = dict(format=unpacker.format)

        if isinstance(unpacker, TarUnpacker):
            result.unpack['skip'] = unpacker.skip

        contents = []

        for entry in unpacker:
            if entry.is_regular_file and entry.is_extractable:
                try:
                    provided = self.add_file(
                        entry.name,
                        opened=unpacker.open(entry),
                        size=entry.size,
                        parent_unpacker=unpacker)
                except NotImplementedError as e:
                    logger.warning("Can't decompress %s from %s: %s" %
                                   (entry.name, result.name, e))
                else:
                    contents.append(provided)

        self.reconcile_groups(
            contents, stem=result.name, provider=result,
        )

    def reconcile_groups(
        self,
        files: Iterable[HashedFile],
        stem: str | None = None,
        provider: WantedFile | None = None,
        package: Package | None = None,
    ) -> None:
        names = set()
        remaining = set()
        groups_found = {}
        optional = set()

        for f in files:
            names.add(f.name)
            remaining.add(f.name)

        # If there are pre-existing groups that are strict subsets of
        # what's left to classify, then take them out, largest first.
        if remaining:
            weighted = []

            for name, g in self.game.groups.items():
                weighted.append((len(g.group_members), g.name, g))

            weighted.sort(reverse=True)

            for _, _, g in weighted:
                if g.group_members <= remaining:
                    remaining -= g.group_members
                    groups_found[g.name] = g

        # If there are pre-existing groups with a non-trivial
        # intersection with what's left to classify, then take those,
        # largest intersection first.
        while remaining:
            weighted = []

            for name, g in self.game.groups.items():
                intersection = g.group_members & remaining

                # Arbitrarily decide that overlaps of less than 5 are
                # uninteresting
                if len(intersection) >= 5:
                    weighted.append((len(intersection), g.name, g))

            if not weighted:
                break

            weighted.sort(reverse=True)

            for _, _, g in weighted:
                intersecting_group = self.new_group(
                    '%s in %s' % (g.name, stem),
                )
                intersecting_group.group_members = g.group_members & names
                groups_found[intersecting_group.name] = intersecting_group
                disjoint_group = self.new_group(
                    '%s not in %s' % (g.name, stem),
                )
                disjoint_group.group_members = g.group_members - names

                remaining -= intersecting_group.group_members

        # If there's anything left, create new groups.
        if remaining:
            prefix = 'remaining ' if groups_found else ''

            main_group = self.new_group('%scontents of %s' % (prefix, stem))
            opt_group = self.new_group(
                '%scontents of %s - optional' % (prefix, stem),
            )
            optional.add(opt_group.name)
            doc_group = self.new_group(
                '%scontents of %s - documentation' % (prefix, stem),
            )
            doc_group.doc = True
            license_group = self.new_group(
                '%scontents of %s - licenses' % (prefix, stem),
            )
            license_group.license = True
            # only from .deb
            abs_group = self.new_group(
                '%scontents of %s - absolute paths' % (prefix, stem),
            )
            abs_group.install_to = '.'
            optional.add(abs_group.name)

            for n in remaining:
                f = self.game.files[n]

                if f.install_to == '.':
                    abs_group.group_members.add(n)
                elif f.license and f.doc:
                    license_group.group_members.add(n)
                    doc_group.group_members.add(n)
                elif f.license:
                    license_group.group_members.add(n)
                elif f.doc:
                    doc_group.group_members.add(n)
                elif f.ignorable or is_probably_optional(f.name):
                    opt_group.group_members.add(n)
                else:
                    main_group.group_members.add(n)

            for g in (
                main_group, opt_group, doc_group, license_group, abs_group,
            ):
                if g.group_members:
                    groups_found[g.name] = g

        # Check that the set of names hasn't changed during this process
        union = set()

        for g in groups_found.values():
            for m in g.group_members:
                union.add(m)

        assert union == names

        if provider:
            provider.provides = set()

            for name, g in groups_found.items():
                if g.group_members:
                    provider.provides.add(name)

            provider.provides_files = set(
                self.game.iter_expand_groups(provider.provides))

        if package:
            for name, g in groups_found.items():
                if g.group_members:
                    if g.license or g.doc or g.ignorable or name in optional:
                        package.optional.add(name)
                    else:
                        package.install.add(name)

    def add_file(
        self,
        path: str,
        out_name: str | None = None,
        opened: BinaryIO | None = None,
        size: int | None = None,
        lang: str | None = None,
        parent_unpacker: StreamUnpackable | None = None,
        unpack: bool = False,
    ) -> WantedFile:
        ignorable = False

        if out_name is None:
            out_name = path

        if is_dosbox(path, opened):
            self.has_dosbox = True
            ignorable = True
        elif os.path.splitext(path.lower())[1] in (
            '.exe', '.exe$0', '.ovl',
            '.dll', '.dll$0', '.bat', '.386',
        ):
            ignorable = True
        elif out_name.startswith('goggame-') or out_name in (
            'webcache.zip', 'gog.ico', 'gfw_high.ico',
        ):
            ignorable = True

        if opened is None:
            is_plain_file = True
            opened = open(path, 'rb')
        else:
            is_plain_file = False

        hf = HashedFile.from_file(path, opened, size=size)
        return self.add_hashed_file(
            path, hf,
            out_name=out_name, lang=lang,
            parent_unpacker=parent_unpacker, size=size,
            is_plain_file=is_plain_file, unpack=unpack, opened=opened,
            ignorable=ignorable,
        )

    def add_hashed_file(
        self,
        path: str,
        hf: HashedFile,
        *,
        out_name: str | None = None,
        lang: str | None = None,
        parent_unpacker: StreamUnpackable | None = None,
        size: int | None = None,
        unpack: bool = False,
        is_plain_file: bool = False,
        opened: BinaryIO | None = None,
        ignorable: bool = False,
    ) -> WantedFile:
        if out_name is None:
            out_name = path

        result = None
        existing = None
        match_path = '/' + path.lower()

        # TODO: This resembles PackagingTask.consider_file()
        # and PackagingTask.use_file()
        for look_for, candidates in self.game.known_filenames.items():
            if match_path.endswith('/' + look_for):
                for c in candidates:
                    existing = self.game.files[c]

                    if hf.matches(existing):
                        # TODO: Show provenance of archive members somehow
                        logger.info('Found %s at %s', existing.name, out_name)

                        if existing.size is None:
                            existing.size = hf.size

                        if existing.md5 is None:
                            existing.md5 = hf.md5

                        if existing.sha1 is None:
                            existing.sha1 = hf.sha1

                        if existing.sha256 is None:
                            existing.sha256 = hf.sha256

                        result = existing
                        break
                    else:
                        existing = None

                if result is not None:
                    break
        else:
            # We are creating a new WantedFile
            assert existing is None
            assert hf.md5 is not None

            for prefix in self.strip_paths:
                if out_name.startswith(prefix + '/'):
                    out_name = out_name[len(prefix) + 1:]

            if out_name not in self.game.files:
                pass
            elif lang and out_name + '?' + lang not in self.game.files:
                out_name += ('?' + lang)

            elif out_name + '?' + hf.md5[:6] not in self.game.files:
                out_name += ('?' + hf.md5[:6])

            else:
                i = 0

                while out_name + '?' + str(i) in self.game.files:
                    i += 1

                out_name += ('?' + str(i))

            assert out_name not in self.game.files

            result = WantedFile(out_name)
            result.size = hf.size
            result.md5 = hf.md5
            result.sha1 = hf.sha1
            result.sha256 = hf.sha256

            if ignorable:
                result.ignorable = True

            self.game.files[result.name] = result

        assert type(result) is WantedFile

        for lf in result.look_for:
            self.game.known_filenames.setdefault(lf, set()).add(result.name)

        if result.md5 is not None:
            self.game.known_md5s.setdefault(result.md5, set()).add(result.name)

        if result.sha1 is not None:
            self.game.known_sha1s.setdefault(result.sha1, set()).add(
                result.name)

        if result.sha256 is not None:
            self.game.known_sha256s.setdefault(result.sha256, set()).add(
                result.name)

        unpacker = None

        if unpack and (parent_unpacker is None or parent_unpacker.seekable()):
            # skip PK3s: we don't normally want to recurse into them
            if not path.endswith('.pk3'):
                if is_plain_file:
                    unpacker = automatic_unpacker(path)
                else:
                    unpacker = automatic_unpacker(path, opened)

        if result is not existing and ignorable:
            result.ignorable = True

        if result is not existing and is_license(path):
            result.license = True

        if result is not existing and is_doc(path):
            result.doc = True

        if unpacker is not None:
            with unpacker:
                self.add_unpacker(path, result, unpacker)

        return result

    def add_template(
        self,
        template: str,
        name: str,
        lower: bool = False
    ) -> None:
        template_game = load_game(
            False, template, None, name=name, yaml_file=template)
        template_game.load_file_data()
        files = {}

        package_name = 'template-%s' % os.path.basename(template)
        i = 0

        while package_name in self.game.packages:
            i += 1
            package_name = 'template-%s-unique%d' % (
                os.path.basename(template), i)

        package = self.game.construct_package(package_name, {})
        self.game.packages[package_name] = package

        for name, f in template_game.files.items():
            files[name] = self.add_hashed_file(
                f.filename, f,
                out_name=name, is_plain_file=False, unpack=False,
                size=f.size,
            )

        for g in template_game.groups.values():
            members = []

            for name in g.group_members:
                if name in files:
                    members.append(files[name])

            self.reconcile_groups(
                members,
                stem='group "' + g.name + '" in ' + os.path.basename(template),
            )

        ungrouped = []

        for name, f in template_game.files.items():
            if f.provides:
                members = []

                for member in f.provides_files:
                    members.append(files[member.name])

                self.reconcile_groups(
                    members,
                    stem='files provided by "%s" in %s' % (
                        name, os.path.basename(template)
                    ),
                    provider=files[f.name],
                )

            for g in template_game.groups.values():
                if name in g.group_members:
                    break
            else:
                ungrouped.append(files[name])

            if f.unpack:
                files[name].unpack = f.unpack

        self.reconcile_groups(
            ungrouped,
            stem='no particular group in ' + os.path.basename(template),
        )

        self.reconcile_groups(
            list(files.values()),
            stem='files listed in ' + os.path.basename(template),
            package=package,
        )

    def add_one_dir(
        self,
        destdir: str,
        lower: bool = False,
        game: str | None = None,
        lang: str | None = None,
        group_stem: str | None = None,
    ) -> None:
        basename = os.path.basename(os.path.abspath(destdir))

        if group_stem is None:
            group_stem = basename

        if destdir.startswith('/usr/local') or destdir.startswith('/opt/'):
            self.game.try_repack_from.append(destdir)

        if not game:
            game = basename

        if game.endswith('-data'):
            game = game[:len(game) - 5]

        steam = max(destdir.find('/SteamApps/common/'),
                    destdir.find('/steamapps/common/'))
        if steam > 0:
            steam_dict: dict[str, int | str] = dict()
            steam_id = 'FIXME'
            for acf in parse_acf(destdir[:steam+11]):
                if '/common/' + acf['installdir'] in destdir:
                    steam_id = acf['appid']
                    self.game.longname = game = acf['name']
                    break
            steam_dict['id'] = int(steam_id)
            steam_dict['path'] = destdir[steam+11:]

        virtual = None
        package = None
        assert game
        game = game.replace(' ', '').replace(':', '').replace('_', '-').lower()

        if lang:
            stem = package_name = game + '-' + lang + '-data'
            virtual = game + '-data'
        else:
            stem = package_name = game + '-data'

        i = 0

        while package_name in self.game.packages:
            i += 1
            package_name = '%s-unique%d' % (stem, i)

        package = self.game.construct_package(package_name, {})
        self.game.packages[package_name] = package

        if lang:
            if lang != 'en':
                package.langs = [lang]

        if virtual:
            package.relations['provides'].append(PackageRelation(virtual))

        if steam > 0:
            package.steam = steam_dict

        contents = []

        for dirpath, dirnames, filenames in os.walk(destdir):
            if self.is_scummvm(dirpath) or is_runtime(dirpath):
                continue

            for fn in filenames:
                path = os.path.join(dirpath, fn)

                assert path.startswith(destdir + '/')
                name = path[len(destdir) + 1:]
                out_name = name
                if lower:
                    out_name = out_name.lower()

                if os.path.isdir(path):
                    continue
                elif os.path.islink(path):
                    package.symlinks[path] = os.path.realpath(path)
                elif os.path.isfile(path):
                    contents.append(
                        self.add_file(path, out_name=out_name, lang=lang))
                else:
                    logger.warning('ignoring unknown file type at %s' % path)

            if self.has_dosbox:
                logger.warning(
                    'DOSBOX files detected, make sure not to include those '
                    'in your package'
                )

        if self.plugin != 'scummvm_common':
            package.install_to = '$assets/' + game

        self.reconcile_groups(contents, group_stem, package=package)

    def add_one_gog_sh(self, archive: str) -> None:
        self.add_archive(archive, unpack=True)

        with zipfile.ZipFile(archive, 'r') as zf:
            if 'scripts/config.lua' in zf.namelist():
                with zf.open('scripts/config.lua') as metadata:
                    for line in metadata.read().decode().splitlines():
                        line = line.strip()
                        if line.startswith('id = '):
                            self.game.gog['path'] = '"%s"' % line.split('"')[1]

    def add_one_innoextract(self, exe: str, lower: bool) -> None:
        game = self.game.gog['game'] = GOG.get_id_from_archive(exe)
        if not game:
            game = os.path.basename(exe)
            game = game[len('setup_'):len(game)-len('.exe')]
            last_part = game.split('_')[-1]
            if last_part.strip('0123456789.') == '':
                game = game[0:len(game)-len(last_part)-1]
            last_part = game.split('_')[-1]
            if last_part in (
                'german',
                'spanish',
                'french',
                'italian',
                'polish',
                'russian',
            ):
                game = game[0:len(game)-len(last_part)-1]

        tmp = tempfile.mkdtemp(prefix='gdptmp.')

        result = self.add_archive(exe, lower, unpack=False)
        logger.info('Unpacking "%s" with innoextract...', exe)

        with InnoSetup(os.path.realpath(exe)) as unpacker:
            log = unpacker._extractall_for_template(tmp)

        self.game.longname = log.split('\n')[0].split('"')[1]

        self.add_one_dir(
            tmp, lang=guess_lang(exe), lower=lower, group_stem=result.name)
        rm_rf(tmp)

        result.unpack = dict(format='innoextract')
        result.provides = set()

    def add_one_deb(self, deb: str, lower: bool) -> None:
        if not ON_DEBIAN or not which('dpkg-deb'):
            exit('.deb analysis is only implemented on Debian.')

        control = None

        result = self.add_archive(deb, unpack=False)

        version = None
        with subprocess.Popen(
            ['dpkg-deb', '--ctrl-tarfile', deb],
            stdout=subprocess.PIPE,
        ) as ctrl_process:
            with tarfile.open(
                deb + '//control.tar.*',
                mode='r|',
                fileobj=ctrl_process.stdout,
            ) as ctrl_tarfile:
                for ctrl_entry in ctrl_tarfile:
                    name = ctrl_entry.name
                    if name == '.':
                        continue

                    if name.startswith('./'):
                        name = name[2:]
                    if name == 'control':
                        reader = ctrl_tarfile.extractfile(ctrl_entry)
                        control = Deb822(reader)
                        print('# data/%s.control.in' % control['package'])
                        version = control['version']
                        if 'Homepage' in control:
                            if 'gog.com/' in control['Homepage']:
                                self.game.gog['url'] = (
                                    control['Homepage'].split('/')[-1]
                                )

                        control.dump(fd=sys.stdout, text_mode=True)
                        print('')
                    elif name == 'preinst':
                        logger.warning('ignoring preinst, not supported yet')
                    elif name == 'md5sums':
                        pass
                    else:
                        logger.warning('unknown control member: %s', name)

        if control is None:
            exit('Could not find DEBIAN/control')

        result.unpack = dict(format='deb')

        package_name = control['package']
        i = 0

        while package_name in self.game.packages:
            i += 1
            package_name = '%s-unique%d' % (control['package'], i)

        package = self.game.construct_package(package_name, {})
        self.game.packages[package_name] = package

        if version:
            package.version = version

        install_to = None
        contents = []

        with DpkgDebUnpacker(deb) as unpacker:
            for entry in unpacker:
                name = entry.name
                if name.startswith('./'):
                    name = name[2:]

                if self.is_scummvm(name) or is_runtime(name):
                    continue
                if (name.startswith('usr/share/doc/') and
                        name.endswith('changelog.gz')):
                    continue
                if (name.startswith('usr/share/doc/') and
                        name.endswith('changelog.Debian.gz')):
                    continue

                if (name.startswith('usr/share/doc/') and
                        name.endswith('copyright')):
                    print('# data/%s.copyright' % control['package'])
                    for line in unpacker.open(entry):
                        print(line.decode('utf-8'), end='')
                    print('')
                    continue

                if entry.is_regular_file and install_to is None:
                    # assume this is the place
                    if name.startswith('usr/share/games/'):
                        there = name[len('usr/share/games/'):]
                        there = there.split('/', 1)[0]
                        install_to = ('usr/share/games/' + there)
                    elif name.startswith('opt/GOG Games/'):
                        there = name[len('opt/GOG Games/'):]
                        there = there.split('/', 1)[0]
                        install_to = ('opt/GOG Games/' + there)
                        self.game.gog['path'] = '"%s"' % there

                target = entry.get_symbolic_link_target()

                if entry.is_regular_file:
                    abs_path = False
                    doc = False
                    ignorable = False
                    license = False

                    if name.startswith('usr/share/doc/'):
                        name = name[len('usr/share/doc/'):]
                        name = name.split('/', 1)[1]
                        doc = True

                    name_l = name.lower()
                    basename_l = os.path.basename(name_l)

                    if os.path.splitext(name_l)[1] in ('.exe', '.bat'):
                        ignorable = True
                    elif (
                        'support/gog' in name_l
                        or os.path.basename(name_l) in (
                            'start.sh', 'uninstall.sh'
                        )
                    ):
                        ignorable = True
                    elif name.startswith('opt/') and is_license(name):
                        name = basename_l
                        license = True
                    elif name.startswith('opt/') and is_doc(name):
                        doc = True
                    elif (not doc and
                            install_to is not None and
                            name.startswith(install_to + '/')):
                        name = name[len(install_to) + 1:]
                        if lower:
                            name = name.lower()
                        if self.game.gog and name.startswith('data/'):
                            name = name[len('data/'):]
                    elif not doc:
                        abs_path = True

                    provided = self.add_file(
                        deb + '//data.tar.*//' + name,
                        out_name=name,
                        opened=unpacker.open(entry),
                        size=entry.size,
                        parent_unpacker=unpacker)

                    if provided.name not in self.preexisting_files:
                        if doc:
                            provided.doc = True

                        if license:
                            provided.license = True

                        if ignorable:
                            provided.ignorable = True

                        if abs_path:
                            provided.install_to = '.'

                    contents.append(provided)
                elif entry.is_directory:
                    pass
                elif target is not None:
                    package.symlinks[name] = os.path.join(
                        os.path.dirname(name), target)
                else:
                    logger.warning(
                        'unhandled data.tar entry type: %s: %s',
                        name, entry.type_indicator,
                    )

        if self.plugin != 'scummvm_common' and install_to is not None:
            package.install_to = os.path.join(
                '/', install_to
            ).replace('/usr/share/games/', '$assets/')

        self.reconcile_groups(
            contents, stem=result.name,
            package=package, provider=result,
        )

    def print_yaml(self) -> None:
        print('---')

        if self.plugin:
            print('plugin: %s' % self.plugin)
            print('')

        data = self.game.to_data(expand=False, include_ignorable=True)

        if data:
            yaml.dump(data, default_flow_style=False, stream=sys.stdout)

        print('\n...')


def do_one_exec(pgm: list[str], lower: bool) -> None:
    print('running:', pgm)
    with subprocess.Popen(
        ['strace', '-e', 'open', '-s', '100'] + pgm,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    ) as proc:
        used = set()
        missing = set()
        while proc.poll() is None:
            stderr = proc.stderr
            assert stderr is not None
            line = stderr.readline().strip()
            if not line.startswith('open('):
                continue
            file = line.split('"')[1]
            file = file.replace('//', '/')
            if file.startswith('/usr/share/scummvm'):
                continue
            if not (
                file.startswith('/usr/share/games')
                or file.startswith('/usr/share/' + pgm[0])
                or file.startswith('/usr/local/')
            ):
                continue
            if 'ENOENT' in line:
                missing.add(file)
            else:
                used.add(file)

        dirs = set()
        print('# used')
        for file in sorted(used):
            dirs.add(os.path.dirname(file))
            print("    - %s" % file)
        if missing:
            print('# missing ?')
            for file in sorted(missing):
                print("    - %s" % file)

        present = set()
        for dir in dirs:
            for dirpath, dirnames, filenames in os.walk(dir):
                for fn in filenames:
                    present.add(os.path.join(dirpath, fn))

        unused = present - used
        if unused:
            print('# not used')
            for file in sorted(unused):
                print("    - %s" % file)


def do_flacsums(destdir: str, lower: bool) -> None:
    if not which('ffmpeg'):
        exit('Install ffmpeg')
    if not which('metaflac'):
        exit('Install metaflac')

    fla_or_flac = '.fla'
    md5s: dict[str, str] = dict()
    done_wav = 0
    done_flac = 0
    for filename in glob.glob(os.path.join(destdir, '*')):
        file = os.path.basename(filename).lower()
        file, ext = os.path.splitext(file)
        if ext == '.wav':
            md5 = check_output(
                ['ffmpeg', '-i', filename, '-f', 'md5', '-'],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            md5 = md5.rstrip().split('=')[1]
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_wav += 1
        if ext == '.flac':
            fla_or_flac = '.flac'
        if ext in ('.fla', '.flac'):
            md5 = check_output(
                ['metaflac', '--show-md5sum', filename],
                text=True,
            )
            md5 = md5.rstrip()
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_flac += 1

    if not md5s:
        exit("Couldn' find any .wav or .flac file")

    print('flacsums: |')
    for file in sorted(md5s.keys()):
        print('  %s  %s' % (md5s[file], file + fla_or_flac))

    print("\n#processed %i .wav and %i .fla[c] files" % (done_wav, done_flac))


def main(
    args: argparse.Namespace,
    games_: dict[str, GameData]  # not used
) -> None:
    # ./run make-template -e -- scummvm -p /usr/share/games/spacequest1/ sq1
    if args.execute:
        do_one_exec(args.args, args.lower)
        return

    if args.flacsums:
        do_flacsums(args.args[0], args.lower)
        return

    if args.base is None:
        game = GameData(
            '__template__',
            dict(
                copyright='© 1970 FIXME',
                packages={},
            ),
        )
    else:
        games = load_games(args.base)

        if args.base not in games:
            raise SystemExit('Unable to load game %r' % args.base)

        game = games[args.base]

    game.load_file_data()
    template = Template(game, strip_paths=args.strip_paths)

    for t in args.templates:
        template.add_template(t, lower=args.lower, name=game.shortname)

    # "./run make-template setup_<game>.exe gog_<game>.deb"
    # will merge files lists
    for arg in args.args:
        basename = os.path.basename(arg)
        if os.path.isdir(arg):
            template.add_one_dir(
                arg.rstrip('/'), args.lower, lang=guess_lang(arg),
            )
        elif arg.endswith('.deb'):
            template.add_one_deb(arg, args.lower)
        elif basename.startswith('setup_') and arg.endswith('.exe'):
            if not which('innoextract'):
                exit('Install innoextract')
            template.add_one_innoextract(arg, lower=args.lower)
        elif basename.startswith('gog_') and arg.endswith('.sh'):
            template.add_one_gog_sh(arg)
        else:
            template.add_archive(arg, lower=args.lower, unpack=True)

    template.print_yaml()
