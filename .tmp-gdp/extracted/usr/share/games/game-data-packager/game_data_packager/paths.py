#!/usr/bin/python3
# encoding=utf-8

# Copyright 2015-2022 Simon McVittie
# Copyright 2015-2016 Alexandre Detiste
# SPDX-License-Identifier: GPL-2.0-or-later

import os

if os.environ.get('GDP_UNINSTALLED'):
    _srcdir = os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )

    CONFIG = os.path.join(_srcdir, 'etc', 'game-data-packager.conf')

    if 'GDP_PKGDATADIR' in os.environ:
        DATADIR = os.environ['GDP_PKGDATADIR']
    else:
        DATADIR = os.path.join(_srcdir, 'out')

    ETCDIR = os.path.join(_srcdir, 'etc')
    ICONS = os.path.join(DATADIR, 'icons')
else:
    CONFIG = '/etc/game-data-packager.conf'

    if 'GDP_PKGDATADIR' in os.environ:
        DATADIR = os.environ['GDP_PKGDATADIR']
    elif os.path.isdir('/usr/share/games/game-data-packager'):
        DATADIR = '/usr/share/games/game-data-packager'
    else:
        DATADIR = '/usr/share/game-data-packager'

    ETCDIR = '/etc/game-data-packager'
    ICONS = DATADIR
