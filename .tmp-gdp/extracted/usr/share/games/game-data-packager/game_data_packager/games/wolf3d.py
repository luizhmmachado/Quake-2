#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..game import (GameData)

if TYPE_CHECKING:
    import argparse

logger = logging.getLogger(__name__)


class Wolf3DGameData(GameData):
    def add_parser(
        self,
        parsers: argparse._SubParsersAction[Any],
        base_parser: argparse.ArgumentParser,
        **kwargs: Any
    ) -> argparse.ArgumentParser:
        parser = super(Wolf3DGameData, self).add_parser(parsers, base_parser)
        parser.add_argument(
            '-f', dest='download', action='store_false',
            help='Require 1wolf14.zip on the command line',
        )
        parser.add_argument(
            '-w', dest='download', action='store_true',
            help='Download 1wolf14.zip (done automatically if necessary)',
        )
        return parser


GAME_DATA_SUBCLASS = Wolf3DGameData
