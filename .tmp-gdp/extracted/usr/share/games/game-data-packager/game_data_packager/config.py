#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import re

from .paths import CONFIG

logger = logging.getLogger(__name__)

COMMENT = re.compile(r'#.*')
OPTION = re.compile('^([A-Z_]+)=(["\']?)(.*)\\2$')


def read_config() -> dict[str, bool | str]:
    """The world's simplest shell script parser.
    """

    config: dict[str, bool | str] = {
        'install': False,
        'preserve': True,
        'verbose': False,
        'install_method': '',
        'gain_root_command': '',
    }

    try:
        with open(CONFIG, encoding='utf-8') as conffile:
            lineno = 0
            for line in conffile:
                lineno += 1
                line = COMMENT.sub('', line)
                line = line.strip()
                if not line:
                    continue
                match = OPTION.match(line)
                if match:
                    k = match.group(1).lower()
                    v = match.group(3)
                    if k in config:
                        if v == 'yes':
                            config[k] = True
                        elif v == 'no':
                            config[k] = False
                        elif k in ('install_method', 'gain_root_command'):
                            config[k] = v
                        else:
                            logger.warning(
                                '%s:%d: unknown option value: %s=%r',
                                CONFIG, lineno, k, v,
                            )
                    else:
                        logger.warning(
                            '%s:%d: unknown option: %s',
                            CONFIG, lineno, k,
                        )
                else:
                    logger.warning(
                        '%s:%d: could not parse line: %r',
                        CONFIG, lineno, line,
                    )
    except OSError:
        pass

    return config
