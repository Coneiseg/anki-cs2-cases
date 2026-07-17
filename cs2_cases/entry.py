"""Anki entry point: build the controller, register the review hook, add the menu
and toolbar balance. Imported and run by __init__ only when running inside Anki."""
from __future__ import annotations

import os

from aqt import mw

from . import controller as controller_mod
from . import data, reviewer_hook, ui

# Add-on folder name (numeric on AnkiWeb, folder name for manual installs).
ADDON_MODULE = __name__.split(".")[0]

_controller = None  # singleton


def get_controller():
    return _controller


def setup():
    global _controller

    # Let the webview fetch our web files and cached assets.
    mw.addonManager.setWebExports(ADDON_MODULE, r"(web|user_files)/.*")

    config = mw.addonManager.getConfig(ADDON_MODULE) or {}
    catalog = data.load_catalog()
    state_path = os.path.join(data.user_files_dir(), "state.json")

    addon_dir = mw.addonManager.addonFromModule(__name__)
    asset_base = "/_addons/%s/user_files/assets/" % addon_dir

    _controller = controller_mod.Controller(
        state_path, config, catalog, asset_base=asset_base
    )

    reviewer_hook.register(get_controller, on_earn=lambda c: ui.refresh_balance(c))
    ui.register(get_controller, addon_dir)
