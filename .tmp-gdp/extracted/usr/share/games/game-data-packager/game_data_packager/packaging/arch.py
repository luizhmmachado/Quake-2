#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
# Copyright © 2016 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import os
import subprocess
import time
from collections.abc import (Iterable)
from typing import (TYPE_CHECKING)

from . import (Compression, PackagingSystem)
from ..util import (
        check_output,
        normalize_permissions,
        rm_rf,
        run_as_root,
        )

if TYPE_CHECKING:
    from . import (PerPackageState)
    from ..data import (Package, PackageRelation)
    from ..game import (GameData)

logger = logging.getLogger(__name__)


class ArchPackaging(PackagingSystem):
    LICENSEDIR = '$datadir/licenses'
    CHECK_CMD = 'namcap'
    INSTALL_CMD = ['pacman', '-S']
    BUILD_DEP = {'bsdtar', 'fakeroot'}
    PACKAGE_MAP = {
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  # XXX
                  }
    ARCH_DECODE = {
                  'all': 'any',
                  'amd64': 'x86_64',
                  'i386': 'i686',
                  }
    ARCH_ENCODE = {
        'any': 'all',
        'x86_64': 'amd64',
        'i686': 'i386',
    }

    def __init__(self, architecture: str | None = None) -> None:
        super(ArchPackaging, self).__init__(architecture=architecture)
        self._contexts = ('arch', 'generic')

    def read_architecture(self) -> str:
        primary = super(ArchPackaging, self).read_architecture()
        # https://wiki.archlinux.org/index.php/Multilib
        if (
            primary == 'amd64'
            and os.path.exists('/usr/lib32/libc.so')
        ):
            self._foreign_architectures = set(['i386'])
        return primary

    def is_installed(self, package: str) -> bool:
        try:
            return subprocess.call(
                ['pacman', '-Q', package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) == 0
        except FileNotFoundError:
            return False
        else:
            return False

    def current_version(self, package: str) -> str | None:
        try:
            version = check_output(['pacman', '-Q', package],
                                   stderr=subprocess.DEVNULL,
                                   text=True).split()[1]
            assert type(version) is str
            return version
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def is_available(self, package: str) -> bool:
        try:
            return subprocess.call(
                ['pacman', '-Si', package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) == 0
        except FileNotFoundError:
            return False
        else:
            return False

    def available_version(self, package: str) -> str | None:
        try:
            remote_info = check_output(['pacman', '-Si', package],
                                       text=True,
                                       env={'LANG': 'C'})
            assert type(remote_info) is str
            for line in remote_info.splitlines():
                k, _, v = line.split(maxsplit=2)
                if k == 'Version':
                    return v

        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None
        else:
            return None

    def install_packages(
        self,
        packages: Iterable[str],
        method: str | None = None,
        gain_root: str = 'su',
        force: bool = False,
    ) -> None:
        run_as_root(['pacman', '-U'] + list(packages), gain_root)

    def format_relation(self, pr: PackageRelation) -> str:
        assert not pr.contextual
        assert not pr.alternatives
        assert type(pr.package) is str

        if pr.version is not None:
            assert '+' not in pr.version, pr.version
            op = pr.version_operator

            if op in ('<<', '>>'):
                op = op[0]

            # Arch Linux doesn't support the dpkg/rpm meaning for ~
            v = pr.version.rstrip('~')
            assert '~' not in pr.version, pr.version

            # foo>=1.0
            return '%s%s%s' % (self.rename_package(pr.package), op, v)

        return self.rename_package(pr.package)

    def __fill_dest_dir_arch(
        self,
        game: GameData,
        package: Package,
        destdir: str,
        compress: Compression,
        arch: str,
    ) -> None:
        PKGINFO = os.path.join(destdir, '.PKGINFO')
        short_desc, _ = self.generate_description(game, package)
        size = check_output(['du', '-bs', '.'], cwd=destdir)
        size = int(size.split()[0])
        with open(PKGINFO, 'w',  encoding='utf-8') as pkginfo:
            pkginfo.write('pkgname = %s\n' % package.name)
            pkginfo.write('pkgver = %s-1\n' % package.version)
            pkginfo.write('pkgdesc = %s\n' % short_desc)
            pkginfo.write(
                'url = https://wiki.debian.org/Games/GameDataPackager\n'
            )
            pkginfo.write('builddate = %i\n' % int(time.time()))
            pkginfo.write(
                'packager = Alexandre Detiste <alexandre@detiste.be>\n'
            )
            pkginfo.write('size = %i\n' % size)
            pkginfo.write('arch = %s\n' % arch)
            if os.path.isdir(os.path.join(destdir, 'usr/share/licenses')):
                pkginfo.write('license = custom\n')
            pkginfo.write('group = games\n')
            if package.expansion_for:
                pkginfo.write('depend = %s\n' % package.expansion_for)
            else:
                engine = self.substitute(
                        package.engine or game.engine,
                        package.name)

                if engine and len(engine.split()) == 1:
                    pkginfo.write('depend = %s\n' % engine)

        files = set()
        for dirpath, dirnames, filenames in os.walk(destdir):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                full = full[len(destdir)+1:]
                files.add(full)

        MTREE = os.path.join(destdir, '.MTREE')
        subprocess.check_call(
            [
                'fakeroot', 'bsdtar', '-czf', MTREE, '--format=mtree',
                ('--options=!all,use-set,type,uid,gid,mode,time,size,md5'
                 ',sha256,link'),
            ] + sorted(files),
            env={'LANG': 'C'},
            cwd=destdir,
        )

    def build_package(
        self,
        per_package_state: PerPackageState,
        game: GameData,
        destination: str,
        compress: Compression = True,
    ) -> str:
        package = per_package_state.package
        destdir = per_package_state.destdir
        arch = self.get_effective_architecture(package)

        self.__fill_dest_dir_arch(game, package, destdir, compress, arch)
        normalize_permissions(destdir)

        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isfile(os.path.join(destdir, '.PKGINFO')), destdir
        assert os.path.isfile(os.path.join(destdir, '.MTREE')), destdir

        if not compress:
            bsdtar_args = []
            ext = ''
        elif compress == ['-Zgzip', '-z1']:
            bsdtar_args = ['--gzip', '--options=compression-level=1']
            ext = '.gz'
        else:
            bsdtar_args = ['--xz']
            ext = '.xz'

        pkg_basename = '%s-%s-1-%s.pkg.tar%s' % (
            package.name, package.version, arch, ext,
        )
        outfile = os.path.join(os.path.abspath(destination), pkg_basename)

        try:
            logger.info('generating package %s', package.name)
            files = set()
            for dirpath, dirnames, filenames in os.walk(destdir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    full = full[len(destdir)+1:]
                    files.add(full)
            check_output(
                ['fakeroot', 'bsdtar', '--create']
                + bsdtar_args
                + ['--file', outfile]
                + sorted(files),
                cwd=destdir,
                env={'LANG': 'C'},
            )
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        rm_rf(destdir)
        return outfile

    def get_libdir(self) -> str:
        return 'lib'


def get_packaging_system(
    distro: str | None = None,
    architecture: str | None = None,
) -> ArchPackaging:
    return ArchPackaging(architecture=architecture)
