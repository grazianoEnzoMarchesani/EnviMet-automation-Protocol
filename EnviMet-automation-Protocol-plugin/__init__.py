# -*- coding: utf-8 -*-
import sys


def classFactory(iface):
    pkg_prefix = __name__ + "."
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(pkg_prefix):
            sys.modules.pop(mod_name, None)

    from .main import EnviProtocol
    return EnviProtocol(iface)
