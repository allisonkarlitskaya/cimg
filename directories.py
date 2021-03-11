# This file is part of Cockpit.
#
# Copyright (C) 2019 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

import os

def xdg_home(subdir, envvar, *components, override=None):
    path = override and os.getenv(override)

    if not path:
        directory = os.getenv(envvar)
        if not directory:
            directory = os.path.join(os.path.expanduser('~'), subdir)
        path = os.path.join(directory, *components)

    return path


def xdg_config_home(*components, envvar=None):
    return xdg_home('.config', 'XDG_CONFIG_HOME', *components, override=envvar)


def xdg_cache_home(*components, envvar=None):
    return xdg_home('.cache', 'XDG_CACHE_HOME', *components, override=envvar)
