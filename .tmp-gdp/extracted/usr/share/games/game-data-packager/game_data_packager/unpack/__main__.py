#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse

from .auto import automatic_unpacker

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output', '-o', help='extract to OUTPUT', default=None)
    parser.add_argument('archive')
    args = parser.parse_args()

    unpacker = automatic_unpacker(args.archive)

    if unpacker is None:
        raise ValueError('Cannot work out how to unpack %r' % args.archive)

    with unpacker:
        if args.output:
            unpacker.extractall(args.output)
        else:
            unpacker.printdir()
