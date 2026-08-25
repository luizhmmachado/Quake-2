#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import os
import stat
import subprocess
from collections.abc import (Iterable)
from typing import (TYPE_CHECKING)

try:
    from debian.deb822 import Deb822
    from debian.debian_support import Version
except ImportError:
    # make check
    Deb822 = None       # type: ignore
    Version = None      # type: ignore

from . import (Compression, PackagingSystem, PerPackageState)
from ..data import (HashedFile)
from ..util import (
        check_output,
        mkdir_p,
        normalize_permissions,
        rm_rf,
        run_as_root)

if TYPE_CHECKING:
    from ..data import (Package, PackageRelation)
    from ..game import (GameData)


logger = logging.getLogger(__name__)


class DebPackaging(PackagingSystem):
    BINDIR = '$prefix/games'
    ASSETS = '$datadir/games'
    CHECK_CMD = 'lintian'
    INSTALL_CMD = ['apt-get', 'install']
    # This is only used when cross-building Debian packages on
    # non-Debian, so conservatively assume that they don't have a new
    # enough dpkg-dev for --root-owner-group
    BUILD_DEP = {'dpkg', 'fakeroot', 'python3-debian'}
    PACKAGE_MAP = {
                  'id-shr-extract': 'dynamite',
                  'lha': 'lhasa',
                  '7z': '7zip',
                  'unrar-nonfree': 'unrar',
                  'zoom': 'zoom-player',
                  'doom': 'doom-engine',
                  'boom': 'boom-engine',
                  'heretic': 'heretic-engine',
                  'hexen': 'hexen-engine',
                  'doomsday-compat': 'doomsday',
                  }
    RENAME_PACKAGES = {
            'libSDL-1.2.so.0': 'libsdl1.2debian',
            'libSDL_mixer-1.2.so.0': 'libsdl-mixer1.2',
            'libSDL_ttf-2.0.so.0': 'libsdl-ttf2.0-0',
            'libgcc_s.so.1': 'libgcc1',
            'libjpeg.so.62': 'libjpeg62-turbo | libjpeg62',
            'libsmpeg-0.4.so.0': 'libsmpeg0',
            'libz.so.1': 'zlib1g',
    }

    def __init__(self, architecture: str | None = None) -> None:
        super(DebPackaging, self).__init__(architecture=architecture)
        self.__installed: set[str] | None = None
        self.__available: set[str] | None = None
        self._contexts = ('deb', 'generic')

    def read_architecture(self) -> str:
        self._architecture = primary = check_output(
            ['dpkg', '--print-architecture']
        ).strip().decode('ascii')
        self._foreign_architectures = set(
            check_output(
                ['dpkg', '--print-foreign-architectures']
            ).strip().decode('ascii').split()
        )
        assert type(primary) is str
        return primary

    def is_installed(self, package: str) -> bool:
        # FIXME: this shouldn't be hard-coded
        if package == 'doom-engine':
            return (
                self.is_installed('chocolate-doom')
                or self.is_installed('crispy-doom')
                or self.is_installed('dsda-doom')
                or self.is_installed('woof-doom')
                or self.is_installed('doomsday')
            )
        if package == 'boom-engine':
            return (
                self.is_installed('dsda-doom')
                or self.is_installed('woof-doom')
                or self.is_installed('doomsday')
            )
        if package == 'heretic-engine':
            return (
                self.is_installed('chocolate-doom')
                or self.is_installed('crispy-doom')
                or self.is_installed('dsda-doom')
                or self.is_installed('doomsday')
            )
        if package == 'hexen-engine':
            return (
                self.is_installed('chocolate-hexen')
                or self.is_installed('crispy-doom')
                or self.is_installed('dsda-doom')
                or self.is_installed('doomsday')
            )

        if os.path.isdir(os.path.join('/usr/share/doc', package)):
            return True

        cache = self.__installed

        if cache is None:
            try:
                proc = subprocess.Popen(
                    ['dpkg-query', '--show', '--showformat', '${Package}\\n'],
                    text=True,
                    close_fds=True,
                    stdout=subprocess.PIPE,
                )
            except FileNotFoundError:
                return False

            cache = set()
            stdout = proc.stdout
            assert stdout is not None
            for line in stdout:
                cache.add(line.rstrip())
            self.__installed = cache
            stdout.close()
            proc.wait()

        return package in cache

    def is_available(self, package: str) -> bool:
        cache = self.__available

        if cache is None:
            try:
                proc = subprocess.Popen(
                    ['apt-cache', 'pkgnames'],
                    text=True,
                    close_fds=True,
                    stdout=subprocess.PIPE,
                )
            except FileNotFoundError:
                return False

            cache = set()
            stdout = proc.stdout
            assert stdout is not None
            for line in stdout:
                cache.add(line.rstrip())
            self.__available = cache
            stdout.close()
            proc.wait()

        return package in cache

    def current_version(self, package: str) -> str | None:
        # 'dpkg-query: no packages found matching $package'
        # will leak on stderr if called with an unknown package,
        # but that should never happen
        try:
            version = check_output(
                [
                    'dpkg-query', '--show', '--showformat', '${Version}',
                    package,
                ],
                text=True)
            assert type(version) is str
            return version
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def available_version(self, package: str) -> str | None:
        try:
            current_ver = check_output(
                ['apt-cache', 'madison', package], text=True,
            )
        except FileNotFoundError:
            return None
        assert type(current_ver) is str
        current_ver = current_ver.splitlines()[0]
        current_ver = current_ver.split('|')[1].strip()
        return current_ver

    def install_packages(
        self,
        debs: Iterable[str],
        method: str | None = 'apt',
        gain_root: str = 'su',
        force: bool = False,
    ) -> None:
        if method is None:
            method = 'apt'
        elif method not in (
            'apt', 'dpkg',
            'gdebi', 'gdebi-gtk', 'gdebi-kde',
        ):
            logger.warning(
                'Unknown installation method %r, using apt instead',
                method,
            )
            method = 'apt'

        if method == 'apt':
            argv = ['apt-get', 'install', '--install-recommends']

            if force:
                argv.append('--assume-yes')

            run_as_root(argv + list(debs), gain_root)
        elif method == 'dpkg':
            run_as_root(['dpkg', '-i'] + list(debs), gain_root)
        elif method == 'gdebi':
            run_as_root(['gdebi'] + list(debs), gain_root)
        else:
            # gdebi-gtk etc.
            subprocess.call([method] + list(debs))

    def rename_package(self, p: str) -> str:
        mapped = super(DebPackaging, self).rename_package(p)

        if mapped != p:
            return mapped

        p = p.lower().replace('_', '-')

        if '.so.' in p:
            lib, version = p.split('.so.', 1)

            if lib[-1] in '012345679':
                lib += '-'

            return lib + version

        return p

    def format_relation(self, pr: PackageRelation) -> str:
        assert not pr.contextual

        if pr.alternatives:
            return ' | '.join(
                [self.format_relation(p) for p in pr.alternatives]
            )

        package = pr.package
        assert package is not None

        if pr.version is not None:
            # foo (>= 1.0)
            return '%s (%s %s)' % (
                self.rename_package(package), pr.version_operator, pr.version,
            )

        return self.rename_package(package)

    def __generate_control(
        self,
        game: GameData,
        package: Package,
        destdir: str,
        component: str,
    ) -> Deb822:
        if Deb822 is None:
            raise FileNotFoundError(
                'Cannot generate .deb packages without python3-debian',
            )

        control = Deb822()
        control['Package'] = package.name
        control['Version'] = package.version
        control['Priority'] = 'optional'
        control['Maintainer'] = \
            'Debian Games Team <pkg-games-devel@lists.alioth.debian.org>'

        installed_size = 0
        # algorithm from https://bugs.debian.org/650077 designed to be
        # filesystem-independent
        for dirpath, dirnames, filenames in os.walk(destdir):
            if dirpath == destdir and 'DEBIAN' in dirnames:
                dirnames.remove('DEBIAN')
            # estimate 1 KiB per directory
            installed_size += len(dirnames)
            for f in filenames:
                stat_res = os.lstat(os.path.join(dirpath, f))
                if (stat.S_ISLNK(stat_res.st_mode) or
                        stat.S_ISREG(stat_res.st_mode)):
                    # take the real size and round up to next 1 KiB
                    installed_size += ((stat_res.st_size + 1023) // 1024)
                else:
                    # this will probably never happen in gdp, but assume
                    # 1 KiB per non-regular, non-directory, non-symlink file
                    installed_size += 1
        control['Installed-Size'] = str(installed_size)

        if component == 'main':
            control['Section'] = package.section
        else:
            control['Section'] = component + '/' + package.section

        if package.architecture == 'all':
            control['Architecture'] = 'all'
            if package.multi_arch is None:
                control['Multi-Arch'] = 'foreign'
        else:
            control['Architecture'] = self.get_architecture(
                    package.architecture)

        if (
            package.multi_arch is not None
            and package.multi_arch != 'no'
        ):
            control['Multi-Arch'] = package.multi_arch

        dep = dict()

        for rel in package.relations:
            if rel == 'build_depends':
                continue

            dep[rel] = self.merge_relations(package, rel)
            logger.debug('%s %s %s', package.name, rel, ', '.join(dep[rel]))

        if package.mutually_exclusive:
            dep['conflicts'] |= package.demo_for
            dep['conflicts'] |= package.better_versions

        if package.mutually_exclusive:
            dep['replaces'] |= dep['provides']

        engine = self.substitute(
                package.engine or game.engine,
                package.name)

        if engine:
            engine_noversion = []
            for e in engine.split(' | '):
                if '>=' in e:
                    e, ver = e.split(maxsplit=1)
                    ver = ver.strip('(>=) ')
                    dep['breaks'].add('%s (<< %s~)' % (e, ver))
                engine_noversion.append(e)
            engine = ' | '.join(engine_noversion)

        # We only 'recommends' & not 'depends'; to avoid
        # that GDP-generated packages get removed
        # if engine goes through some gcc/png/ffmpeg/... migration
        # and must be temporarily removed.
        # It's not like 'apt-get install ...' can revert this removal;
        # user may need to dig again for the original media....
        if package.engine:
            assert engine is not None
            dep['recommends'].add(engine)
        elif game.engine and (
            package.section != 'doc'
            and not package.expansion_for
        ):
            assert engine is not None
            dep['recommends'].add(engine)

        if package.expansion_for:
            # check if default heuristic has been overriden in yaml
            for p in dep['depends']:
                if package.expansion_for == p.split()[0]:
                    break
            else:
                dep['depends'].add(package.expansion_for)

        # dependencies derived from *other* package's data
        for other_package in game.packages.values():
            if other_package.expansion_for:
                if package.name == other_package.expansion_for:
                    dep['suggests'].add(other_package.name)
                else:
                    for relp in package.relations['provides']:
                        if relp.package == other_package.expansion_for:
                            dep['suggests'].add(other_package.name)

            if other_package.mutually_exclusive:
                if package.name in other_package.better_versions:
                    dep['replaces'].add(other_package.name)

                if package.name in other_package.demo_for:
                    dep['replaces'].add(other_package.name)

        # Shortcut: if A Replaces B, A automatically Conflicts B
        dep['conflicts'] |= dep['replaces']

        # keep only strongest depedency
        dep['recommends'] -= dep['depends']
        dep['suggests'] -= dep['recommends']
        dep['suggests'] -= dep['depends']

        for k, v in dep.items():
            if v:
                control[k.title()] = ', '.join(sorted(v))

        if 'Description' not in control:
            short_desc, long_desc = self.generate_description(game, package)
            control['Description'] = (
                short_desc + '\n '
                + '\n '.join([(line or '.') for line in long_desc]))

        return control

    def __fill_dest_dir_deb(
        self,
        game: GameData,
        per_package_state: PerPackageState,
    ) -> None:
        component = per_package_state.component
        destdir = per_package_state.destdir
        md5sums = per_package_state.md5sums
        package = per_package_state.package

        if component is None:
            component = package.component

        if component == 'local':
            per_package_state.lintian_overrides.add(
                'unknown-section local/{}'.format(
                    package.section,
                )
            )

        for o in sorted(per_package_state.lintian_overrides):
            lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
            mkdir_p(lintiandir)

            with open(
                os.path.join(lintiandir, package.name),
                'a',
                encoding='utf-8'
            ) as writer:
                writer.write('%s: %s\n' % (package.name, o))

        # same output as in dh_md5sums
        if md5sums is None:
            md5sums = {}

        # we only compute here the md5 we don't have yet,
        # for the (small) GDP-generated files
        for dirpath, dirnames, filenames in os.walk(destdir):
            if os.path.basename(dirpath) == 'DEBIAN':
                continue
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if os.path.islink(full):
                    continue
                file = full[len(destdir)+1:]
                if file not in md5sums:
                    with open(full, 'rb') as opened:
                        hf = HashedFile.from_file(full, opened)
                        md5 = hf.md5
                        assert md5 is not None
                        md5sums[file] = md5

        debdir = os.path.join(destdir, 'DEBIAN')
        mkdir_p(debdir)
        md5sums_path = os.path.join(destdir, 'DEBIAN/md5sums')
        with open(md5sums_path, 'w', encoding='utf8') as outfile:
            for file in sorted(md5sums.keys()):
                outfile.write('%s  %s\n' % (md5sums[file], file))
        os.chmod(md5sums_path, 0o644)

        control = os.path.join(destdir, 'DEBIAN/control')
        with open(control, 'wb') as fd:
            self.__generate_control(game, package, destdir, component).dump(
                    fd=fd, encoding='utf-8')
        os.chmod(control, 0o644)

    def build_package(
        self,
        per_package_state: PerPackageState,
        game: GameData,
        destination: str,
        compress: Compression = True,
    ) -> str:
        if Version is None:
            raise FileNotFoundError(
                'Cannot generate .deb packages without python3-debian',
            )

        destdir = per_package_state.destdir
        package = per_package_state.package
        arch = self.get_effective_architecture(package)
        self.__fill_dest_dir_deb(game, per_package_state)
        normalize_permissions(destdir)

        # it had better have a /usr and a DEBIAN directory or
        # something has gone very wrong
        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

        deb_basename = '%s_%s_%s.deb' % (package.name, package.version, arch)

        outfile = os.path.join(os.path.abspath(destination), deb_basename)

        if not compress:
            dpkg_deb_args = ['-Znone']
        elif compress is True:
            dpkg_deb_args = []
        elif isinstance(compress, str):
            dpkg_deb_args = ['-Z' + compress]
        elif isinstance(compress, list):
            dpkg_deb_args = compress[:]

        dpkg_deb_args.insert(0, 'dpkg-deb')

        dpkg_version = Version(self.current_version('dpkg'))

        if dpkg_version >= Version('1.19.0'):
            dpkg_deb_args.append('--root-owner-group')
        else:
            dpkg_deb_args.insert(0, 'fakeroot')

        try:
            logger.info('generating package %s', package.name)
            check_output(
                    dpkg_deb_args +
                    ['-b', 'DESTDIR', outfile],
                    cwd=per_package_state.per_package_dir)
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        rm_rf(destdir)
        return outfile

    def available_version_at_least(
        self,
        package: str,
        desired: str,
        *,
        is_installed: bool | None = None,
    ) -> bool:
        if Version is None:
            # Stub: assume yes it is
            return True

        if is_installed is None:
            is_installed = self.is_installed(package)

        if is_installed:
            current_ver = self.current_version(package)
        else:
            current_ver = self.available_version(package)

        # We automatically add a '~' suffix so that ">= 1.0-1" in the YAML
        # really means ">= 1.0-1~" on Debian, while not breaking packaging
        # systems that don't support the RPM/dpkg meaning of '~'
        if current_ver and Version(current_ver) >= Version(desired + '~'):
            return True

        return False

    def get_libdir(self) -> str:
        return os.path.join('lib', check_output(
            ['dpkg-architecture', '-q', 'DEB_BUILD_MULTIARCH']
        ).strip().decode('ascii'))


def get_packaging_system(
    distro: str | None = None,
    architecture: str | None = None
) -> PackagingSystem:
    return DebPackaging(architecture=architecture)
