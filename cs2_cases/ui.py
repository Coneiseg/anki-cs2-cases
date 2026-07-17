"""Anki-facing UI.

The market (store / inventory / trade-ups) lives in a dockable sidebar panel. Opening
a case launches a separate frameless overlay that covers the whole Anki window, so the
reel + reveal play seamlessly on top of Anki rather than inside the narrow panel.

Both webviews run the same page in different modes (``window.__MODE__``) and talk to
Python over ``pycmd('cs2:<action>:<json>')``; Python performs the authoritative action
and pushes results back with ``web.eval``.
"""
from __future__ import annotations

import json
import os

from aqt import gui_hooks, mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAction, QColor, QDockWidget, QRect, Qt, QVBoxLayout, QWidget,
)
from aqt.utils import qconnect, showWarning, tooltip
from aqt.webview import AnkiWebView

try:
    from aqt.qt import QWebEngineSettings
except Exception:  # older/newer Qt layout
    QWebEngineSettings = None

from . import data, economy


def _allow_autoplay(web):
    """Let this webview play sound without a prior user gesture in its own context
    (the open click happens in the panel, not the overlay)."""
    if QWebEngineSettings is None:
        return
    try:
        web.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    except Exception:
        pass

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

_get_controller = None
_addon_dir = None
_dock = None       # QDockWidget (sidebar market)
_panel = None      # AnkiWebView inside the dock
_overlay = None    # OpeningOverlay (full-window opening animation)


# --- helpers ---------------------------------------------------------------

def _read_web_file(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def _build_html(mode):
    """Full page for a given mode ('market' or 'overlay'), with CSS/JS inlined and the
    boot state + mode injected so first paint never waits on the bridge."""
    html = _read_web_file("index.html")
    css = _read_web_file("styles.css").replace("__ADDON_DIR__", _addon_dir or "")
    js = _read_web_file("app.js")
    boot = json.dumps(_get_controller().state_payload()).replace("</", "<\\/")
    prefix = "window.__MODE__=%s;\nwindow.__BOOT_STATE__=%s;\n" % (json.dumps(mode), boot)
    return html.replace("/*__CSS__*/", css).replace("//__JS__", prefix + js)


def _parse(cmd):
    if not isinstance(cmd, str) or not cmd.startswith("cs2:"):
        return None, None
    parts = cmd.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    args = {}
    if len(parts) > 2 and parts[2]:
        try:
            args = json.loads(parts[2])
        except ValueError:
            args = {}
    return action, args


def _send(web, action, payload):
    web.eval("window.cs2 && window.cs2.on(%s, %s);" % (json.dumps(action), json.dumps(payload)))


def _panel_state():
    if _panel is not None:
        _send(_panel, "state", {"ok": True, "state": _get_controller().state_payload()})


# --- registration ----------------------------------------------------------

def register(get_controller, addon_dir):
    global _get_controller, _addon_dir
    _get_controller = get_controller
    _addon_dir = addon_dir

    action = QAction("CS2 Cases", mw)
    qconnect(action.triggered, toggle_panel)
    mw.form.menuTools.addAction(action)

    update_action = QAction("CS2 Cases: Update catalog (download real cases)", mw)
    qconnect(update_action.triggered, update_catalog)
    mw.form.menuTools.addAction(update_action)

    gui_hooks.top_toolbar_did_init_links.append(_add_toolbar_balance)
    _ensure_overlay()  # build eagerly so it is loaded before the first open
    _redraw_toolbar()


def _add_toolbar_balance(links, toolbar):
    # Just a plain star — no money shown in Anki's own toolbar.
    links.append(toolbar.create_link(
        "cs2_balance", "★", toggle_panel,
        tip="CS2 Cases — toggle the market", id="cs2_balance",
    ))


def _redraw_toolbar():
    try:
        mw.toolbar.draw()
    except Exception:
        pass


def refresh_balance(controller):
    """Called after earning a card: keep the open panel's balance in sync. The toolbar
    star is static, so it never needs redrawing here."""
    if _dock is not None and _dock.isVisible():
        _panel_state()


# --- sidebar market panel --------------------------------------------------

def _ensure_dock():
    global _dock, _panel
    if _dock is not None:
        return
    _dock = QDockWidget("CS2 Cases", mw)
    _dock.setObjectName("cs2CasesDock")
    _dock.setMinimumWidth(300)
    _dock.setAllowedAreas(
        Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
    _dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable)
    _panel = AnkiWebView(parent=_dock)
    _panel.setMinimumWidth(300)
    _allow_autoplay(_panel)
    _panel.set_bridge_command(_on_panel_bridge, _dock)
    _dock.setWidget(_panel)
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _dock)
    _dock.hide()


def _reload_panel():
    if _panel is not None:
        _panel.stdHtml(_build_html("market"))


def toggle_panel(*_args):
    if _get_controller() is None:
        return
    _ensure_dock()
    if _dock.isVisible():
        _dock.hide()
    else:
        _reload_panel()          # rebuild with fresh balance/inventory
        if _dock.isFloating():   # snap a popped-out panel back into the sidebar
            _dock.setFloating(False)
        _dock.show()
        _dock.raise_()
        try:  # give it a comfortable width the first time it opens
            mw.resizeDocks([_dock], [380], Qt.Orientation.Horizontal)
        except Exception:
            pass


def _on_panel_bridge(cmd):
    action, args = _parse(cmd)
    if action is None:
        return
    if action == "open":
        _launch_open(args.get("case_id"))
        return
    if action == "refresh":
        update_catalog()
        return
    if action == "trade_up":
        _launch_tradeup(args.get("uids"))
        return
    c = _get_controller()
    try:
        if action == "state":
            res = {"state": c.state_payload()}
        elif action == "sell":
            res = c.sell(args["uid"]); res["state"] = c.state_payload()
        elif action == "sell_many":
            res = c.sell_many(args["uids"]); res["state"] = c.state_payload()
        elif action == "favorite":
            res = c.set_favorite(args["uids"], args.get("value", True))
            res["state"] = c.state_payload()
        elif action == "case_detail":
            case = next((x for x in c.catalog["cases"]
                         if x["id"] == args.get("case_id")), None)
            if case is None:
                res = {"ignored": action}
            else:
                res = {"case_detail": {
                    "id": case["id"], "name": case["name"],
                    "price": economy.case_price(case, c.catalog),
                    "items": case["items"],
                    "odds": case.get("odds", {}),
                }}
        elif action == "set_config":
            key, value = args.get("key"), bool(args.get("value"))
            if key in ("muted", "reduced_motion"):
                cfg = mw.addonManager.getConfig(_addon_dir) or {}
                cfg[key] = value
                mw.addonManager.writeConfig(_addon_dir, cfg)
                c.config[key] = value                 # live-update the engine
                if _overlay is not None:
                    _overlay.rebuild()                # so the overlay honors it too
            res = {"state": c.state_payload()}
        else:
            res = {"ignored": action}
        res["ok"] = True
    except economy.EconomyError as exc:
        res = {"ok": False, "error": str(exc)}
    except Exception as exc:  # defensive: never crash the reviewer
        res = {"ok": False, "error": "Unexpected error: %s" % exc}
    _send(_panel, action, res)


def _launch_open(case_id):
    c = _get_controller()
    try:
        result = c.open_case(case_id)
    except economy.EconomyError as exc:
        _send(_panel, "open", {"ok": False, "error": str(exc)})
        return
    _panel_state()  # balance/inventory update behind the overlay
    _ensure_overlay()
    _overlay.play(result["drop"], result["reel"])


def _launch_tradeup(uids):
    c = _get_controller()
    try:
        result = c.trade_up(uids)
    except economy.EconomyError as exc:
        _send(_panel, "trade_up", {"ok": False, "error": str(exc)})
        return
    _panel_state()
    _ensure_overlay()
    _overlay.reveal(result["output"])


# --- full-window opening overlay -------------------------------------------

class OpeningOverlay(QWidget):
    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(mw, flags)
        # Translucent so the reel plays over Anki instead of a solid screen.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web = AnkiWebView(parent=self)
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        try:
            self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))
        except Exception:
            pass
        _allow_autoplay(self.web)
        layout.addWidget(self.web)
        self.web.set_bridge_command(self._bridge, self)
        self.web.stdHtml(_build_html("overlay"))

    def rebuild(self):
        self.web.stdHtml(_build_html("overlay"))

    def _cover(self):
        tl = mw.mapToGlobal(mw.rect().topLeft())
        self.setGeometry(QRect(tl.x(), tl.y(), mw.width(), mw.height()))

    def play(self, drop, reel):
        self._cover()
        self.show(); self.raise_(); self.activateWindow()
        payload = json.dumps({"ok": True, "drop": drop, "reel": reel}).replace("</", "<\\/")
        self.web.eval("window.cs2 && window.cs2.on('play', %s);" % payload)

    def reveal(self, drop):
        """Trade-up result: a reveal (no reel) over Anki, in the output tier's color/sound."""
        self._cover()
        self.show(); self.raise_(); self.activateWindow()
        payload = json.dumps({"ok": True, "drop": drop}).replace("</", "<\\/")
        self.web.eval("window.cs2 && window.cs2.on('tradeup', %s);" % payload)

    def _bridge(self, cmd):
        action, args = _parse(cmd)
        if action == "overlay_reopen":
            c = _get_controller()
            try:
                result = c.open_case(args.get("case_id"))
            except economy.EconomyError as exc:
                _send(self.web, "reopen_error", {"ok": False, "error": str(exc)})
                return
            _panel_state()
            self.play(result["drop"], result["reel"])
            return
        if action == "overlay_sell":
            try:
                _get_controller().sell(args["uid"])
            except Exception:
                pass
        if action in ("overlay_done", "overlay_sell"):
            self.hide()
            _panel_state()


def _ensure_overlay():
    global _overlay
    if _overlay is None:
        _overlay = OpeningOverlay()


# --- catalog update --------------------------------------------------------

def update_catalog(*_args):
    """Download the full real catalog off the main thread, then hot-swap it in."""
    def _op(_col):
        return data.refresh_catalog()

    def _done(summary):
        if not summary.get("ok"):
            showWarning("Catalog update failed:\n%s" % summary.get("error"))
            return
        controller = _get_controller()
        if controller is not None:
            controller.reload_catalog(data.load_catalog())
        if _overlay is not None:
            _overlay.rebuild()
        if _dock is not None and _dock.isVisible():
            _reload_panel()
        tooltip("CS2 Cases: loaded %d cases, cached %d images."
                % (summary.get("cases", 0), summary.get("images", 0)))

    QueryOp(parent=mw, op=_op, success=_done) \
        .with_progress("Downloading CS2 catalog, prices + images (one-time, ~1-2 min)…") \
        .run_in_background()
