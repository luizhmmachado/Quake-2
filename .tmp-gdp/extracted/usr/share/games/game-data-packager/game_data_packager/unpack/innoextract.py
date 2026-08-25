#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2018 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection
from types import TracebackType

from . import (SimpleUnpackable)


class InnoSetup(SimpleUnpackable):
    """Object representing an InnoSetup installer.
    """

    def __init__(
        self,
        path: str | bytes,
        verbose: bool = False,
        language: str | None = None,
    ) -> None:
        """Constructor.

        path may be a string or bytes object.
        """
        self.path = path
        self.verbose = verbose
        self.language = language

    def __enter__(self) -> InnoSetup:
        return self

    def __exit__(
        self,
        _et: type[BaseException] | None = None,
        _ev: BaseException | None = None,
        _tb: TracebackType | None = None
    ) -> None:
        pass

    def _extactall_argv(
        self,
        dest_path: str,
    ) -> list[str]:
        assert type(self.path) is str  # this contradicts  __init__ #L46
        return [
            'innoextract',
            '-T', 'local',
            '-d', dest_path,
            self.path,
        ]

    def _extractall_for_template(
        self,
        path: str
    ) -> str:
        argv = self._extactall_argv(path)
        argv.append('--collisions=rename')

        res = subprocess.check_output(
            argv,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert type(res) is str
        return res

    def extractall(
        self,
        path: str,
        members: Collection[str] | None = None,
    ) -> None:
        argv = self._extactall_argv(path)

        if members is not None:
            for member in members:
                argv.append('-I')
                argv.append(member)

        if not self.verbose:
            argv.append('--silent')
            argv.append('--progress')

        if self.language is not None:
            argv.append('--language')
            argv.append(self.language)

        subprocess.check_call(argv)

    def printdir(self) -> None:
        subprocess.check_call([
            'innoextract',
            '--default-language', (self.language or 'english'),
            '-T', 'local',
            '--list',
            self.path,
        ])

    def search_for_gog_icon(self) -> str | None:
        result = subprocess.run([
            'innoextract',
            '--default-language', (self.language or 'english'),
            '-T', 'local',
            '--list',
            self.path,
        ], capture_output=True, check=True)
        match = re.search(
                    r' "([0-9A-Za-z/]*goggame-\d*.ico)" ',
                    result.stdout.decode()
                )
        if match:
            return match.group(1)
        return None

    @property
    def format(self) -> str:
        return 'innoextract'


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output', '-o', help='extract to OUTPUT', default=None)
    parser.add_argument(
        '--verbose', '-v', help='Be verbose', action='store_true')
    parser.add_argument('setup_exe')
    args = parser.parse_args()

    setup = InnoSetup(args.setup_exe, verbose=args.verbose)

    if args.output:
        setup.extractall(args.output)
    else:
        setup.printdir()
