#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# SPDX-License-Identifier: GPL-2.0-or-later

import grp
import logging
import os
import shlex
import shutil
import stat
import subprocess
import sys
import yaml
from types import TracebackType
from typing import (Any, TextIO, Type)

SafeLoader: Type[yaml.CSafeLoader] | Type[yaml.SafeLoader]

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

from .paths import DATADIR  # noqa: E402
from .version import (GAME_PACKAGE_VERSION, GAME_PACKAGE_RELEASE)  # noqa: E402

logger = logging.getLogger(__name__)

KIBIBYTE = 1024
MEBIBYTE = KIBIBYTE * KIBIBYTE

AGENT = (
    'Debian Game-Data-Packager/%s%s (%s %s;'
    ' +http://wiki.debian.org/Games/GameDataPackager)'
    % (
        GAME_PACKAGE_VERSION,
        GAME_PACKAGE_RELEASE,
        os.uname()[0],
        os.uname()[4],
    )
)


class TemporaryUmask:
    """Context manager to set the umask. Not thread-safe.

    Use like this::

        with TemporaryUmask(0o022):
            os.makedirs('usr/share/misc')
    """

    def __init__(self, desired_mask: int) -> None:
        self.desired_mask = desired_mask
        self.saved_mask: int | None = None

    def __enter__(self) -> None:
        self.saved_mask = os.umask(self.desired_mask)

    def __exit__(
        self,
        _et: type[BaseException] | None = None,
        _ev: BaseException | None = None,
        _tb: TracebackType | None = None
    ) -> None:
        saved_mask = self.saved_mask

        if saved_mask is not None:
            os.umask(saved_mask)


def load_yaml(stream: TextIO | str) -> Any:
    return yaml.load(stream, Loader=SafeLoader)


def mkdir_p(path: str) -> None:
    if not os.path.isdir(path):
        with TemporaryUmask(0o022):
            os.makedirs(path)


def rm_rf(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)


def human_size(size: int) -> str:
    # 0.0 KiB up to 1024.0 KiB
    if size < MEBIBYTE:
        return '%.1f KiB' % (size / KIBIBYTE)

    # 1.0 MiB or more
    return '%.1f MiB' % (size / (MEBIBYTE))


def copy_with_substitutions(from_: TextIO, to: TextIO, **kwargs: str) -> None:
    for line in from_:
        for k, v in kwargs.items():
            line = line.replace(k, v)
        to.write(line)


__cached_prefered_langs: list[str] | None = None


# Keep in sync with runtime/gdp_launcher_base.py
def prefered_langs() -> list[str]:
    global __cached_prefered_langs

    if __cached_prefered_langs is not None:
        return __cached_prefered_langs

    lang_raw: list[str] = []
    if 'LANGUAGE' in os.environ:
        lang_raw = os.environ['LANGUAGE'].split(':')
    if 'LANG' in os.environ:
        lang_raw.append(os.environ['LANG'])
    lang_raw.append('en')

    __cached_prefered_langs = []
    for lang in lang_raw:
        lang = lang.split('.')[0]
        if not lang or lang == 'C':
            continue
        if lang not in __cached_prefered_langs:
            __cached_prefered_langs.append(lang)
        lang = lang[0:2]
        if lang not in __cached_prefered_langs:
            __cached_prefered_langs.append(lang)

    return __cached_prefered_langs


def lang_score(lang: str) -> int:
    langs = prefered_langs()

    if lang in langs:
        return len(langs) - langs.index(lang)

    lang = lang[0:2]
    if lang in langs:
        return len(langs) - langs.index(lang)

    return 0


def ascii_safe(string: str, force: bool = False) -> str:
    if sys.stdout.encoding != 'UTF-8' or force:
        string = string.translate(
            str.maketrans(
                'àäçčéèêëîïíôöōłñù§┏┛',
                'aacceeeeiiiooolnu***',
            )
        )
    return string


def run_as_root(argv: list[str], gain_root: str = '') -> None:
    if not gain_root and shutil.which('pkexec') is not None:
        # Use pkexec if possible. It has desktop integration, and will
        # prompt for the user's password if they are administratively
        # privileged (a member of group sudo), or root's password
        # otherwise.
        gain_root = 'pkexec'

    if not gain_root and shutil.which('sudo') is not None:
        # Use sudo as the next choice after pkexec, but only if we're in
        # a group that should be able to use it.
        try:
            sudo_group = grp.getgrnam('sudo')
        except KeyError:
            pass
        else:
            if sudo_group.gr_gid in os.getgroups():
                gain_root = 'sudo'

        # If we are in the admin group, also use sudo, but only
        # if this looks like Ubuntu. We use dpkg-vendor at build time
        # to detect Ubuntu derivatives.
        try:
            admin_group = grp.getgrnam('admin')
        except KeyError:
            pass
        else:
            if (admin_group.gr_gid in os.getgroups() and
                    os.path.exists(
                        os.path.join(DATADIR, 'is-ubuntu-derived'))):
                gain_root = 'sudo'

    if not gain_root:
        # Use su if we don't have anything better.
        gain_root = 'su'

    if gain_root not in ('su', 'pkexec', 'sudo', 'super', 'really'):
        logger.warning(
            'Unknown privilege escalation method %r, assuming it works '
            'like sudo',
            gain_root)

    if gain_root == 'su':
        print('using su to obtain root privileges and install the package(s)')

        # su expects a single sh(1) command-line
        cmd = ' '.join([shlex.quote(arg) for arg in argv])

        subprocess.call(['su', '-c', cmd])
    else:
        # this code path works for pkexec, sudo, super, really;
        # we assume everything else is the same
        print(
            'using %s to obtain root privileges and install the package(s)' %
            gain_root)
        subprocess.call([gain_root] + list(argv))


def check_call(command: list[str], *args: Any, **kwargs: Any) -> None:
    """Like subprocess.check_call, but log what we will do first."""
    logger.debug('%r', command)
    subprocess.check_call(command, *args, **kwargs)


def check_output(command: list[str], *args: Any, **kwargs: Any) -> Any:
    """Like subprocess.check_output, but log what we will do first."""
    logger.debug('%r', command)
    return subprocess.check_output(command, *args, **kwargs)


def recursive_utime(
    directory: str,
    orig_time: float | tuple[float, float],
) -> None:
    """Recursively set the access and modification times of everything
    in directory to orig_time.

    orig_time may be a tuple (atime, mtime), or a single int or float.
    """
    if isinstance(orig_time, (int, float)):
        orig_time = (orig_time, orig_time)

    for dirpath, dirnames, filenames in os.walk(directory):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            os.utime(full, orig_time)


def normalize_permissions(directory: str) -> None:
    for dirpath, dirnames, filenames in os.walk(directory):
        for fn in filenames + dirnames:
            full = os.path.join(dirpath, fn)
            stat_res = os.lstat(full)
            if stat.S_ISLNK(stat_res.st_mode):
                continue
            elif stat.S_ISDIR(stat_res.st_mode):
                # make directories rwxr-xr-x
                os.chmod(full, 0o755)
            elif (stat.S_IMODE(stat_res.st_mode) & 0o111) != 0:
                # make executable files rwxr-xr-x
                os.chmod(full, 0o755)
            else:
                # make other files rw-r--r--
                os.chmod(full, 0o644)
