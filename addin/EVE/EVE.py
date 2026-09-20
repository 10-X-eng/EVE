"""Fusion entry point. All Fusion operations stay on the main thread."""
import json
from pathlib import Path
import threading
import traceback

import adsk.core

from .eve.controller import Controller
from .eve.fusion_tools import FusionTools
from .eve.clipboard import read_clipboard_image
from .eve.version import VERSION

COMMAND_ID = "10X_EVE_Open"
PALETTE_ID = "10X_EVE_Panel"
EVENT_ID = "10X_EVE_State"
_app = None
_controller = None
_fusion_tools = None
_palette = None
_handlers = []
_palette_handlers = []
_pending_state = None
_pending_clipboard = None
_clipboard_busy = False
_pending_lock = threading.Lock()
_event_pending = False
_running = False
_want_visible = False


def _log_error():
    if _controller:
        _controller.debug.record("addin.error", traceback=traceback.format_exc())
    if _app:
        _app.log("EVE: " + traceback.format_exc())


def _publish(state):
    global _pending_state, _event_pending
    with _pending_lock:
        _pending_state = state
        if _event_pending or not _running:
            return
        _event_pending = True
    # Autodesk's supported exception for notifying the Fusion thread.
    try:
        _app.fireCustomEvent(EVENT_ID)
    except RuntimeError:
        with _pending_lock:
            _event_pending = False


def _bind(event, handler, collection):
    event.add(handler)
    collection.append((event, handler))


def _unbind(collection):
    for event, handler in collection:
        try:
            event.remove(handler)
        except RuntimeError:
            pass
    collection.clear()


class StateEvent(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _event_pending, _pending_clipboard, _clipboard_busy
        with _pending_lock:
            state = _pending_state
            clipboard = _pending_clipboard
            _pending_clipboard = None
            if clipboard is not None:
                _clipboard_busy = False
            _event_pending = False
        if state and _palette and _palette.isValid:
            try:
                _palette.sendInfoToHTML("state", json.dumps(state, ensure_ascii=False))
            except RuntimeError:
                # The document may still be loading; its ready message requests a fresh snapshot.
                pass
        if clipboard and _palette and _palette.isValid:
            try:
                _palette.sendInfoToHTML("clipboardImage", json.dumps(clipboard))
            except RuntimeError:
                pass


def _read_pasted_image(request_id, controller):
    global _pending_clipboard
    controller.debug.record("clipboard.paste", outcome="requested")
    try:
        image = read_clipboard_image()
        result = {"requestId": request_id, "image": image}
        controller.debug.record("clipboard.image", outcome="image" if image else "empty")
    except Exception as exc:
        result = {"requestId": request_id, "error": str(exc)}
        controller.debug.record("clipboard.image", outcome="error", error=str(exc))
    with _pending_lock:
        if not _running or controller is not _controller:
            return
        _pending_clipboard = result
    _publish(controller.snapshot())


class HTMLMessage(adsk.core.HTMLEventHandler):
    def notify(self, args):
        global _clipboard_busy
        try:
            event = adsk.core.HTMLEventArgs.cast(args)
            payload = json.loads(event.data or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Invalid EVE message.")
            if event.action == "clipboardImage":
                request_id = payload.get("requestId")
                if set(payload) != {"requestId"} or not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
                    raise ValueError("Invalid paste request.")
                if _clipboard_busy:
                    raise ValueError("An image paste is already in progress.")
                _clipboard_busy = True
                try:
                    threading.Thread(target=_read_pasted_image, args=(request_id, _controller), daemon=True).start()
                except Exception:
                    _clipboard_busy = False
                    raise
                event.returnData = json.dumps({"ok": True})
            elif event.action == "imageAssets":
                event.returnData = json.dumps({"ok": True, "images": _controller.image_assets(payload.get("ids"))})
            else:
                accepted = _controller.dispatch(event.action, payload, capture_context=_fusion_tools.message_context)
                if accepted is False:
                    raise ValueError("EVE is already starting a response. Your draft has been kept.")
                event.returnData = json.dumps({"ok": True})
        except Exception as exc:
            _log_error()
            args.returnData = json.dumps({"ok": False, "error": str(exc)})


class PaletteClosed(adsk.core.UserInterfaceGeneralEventHandler):
    def notify(self, args):
        global _want_visible
        _want_visible = False


def _show_palette():
    global _palette, _want_visible
    if not _palette or not _palette.isValid:
        _unbind(_palette_handlers)
        path = (Path(__file__).parent / "panel" / "index.html").resolve().as_uri()
        _palette = _app.userInterface.palettes.add(PALETTE_ID, "EVE", path, False, True, True, 440, 760, True)
        _palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        _bind(_palette.incomingFromHTML, HTMLMessage(), _palette_handlers)
        _bind(_palette.closed, PaletteClosed(), _palette_handlers)
    _palette.isVisible = True
    _want_visible = True
    _controller.dispatch("sync")


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _show_palette()
        except Exception:
            _log_error()


class CommandCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        handler = Execute()
        args.command.execute.add(handler)
        # Retain the handler for the short-lived Fusion command.
        self.execute_handler = handler


class WorkspaceActivated(adsk.core.WorkspaceEventHandler):
    def notify(self, args):
        if _want_visible:
            try:
                _show_palette()
            except Exception:
                _log_error()


def run(context):
    global _app, _controller, _running, _fusion_tools
    try:
        _app = adsk.core.Application.get()
        _running = True
        custom = _app.registerCustomEvent(EVENT_ID)
        _bind(custom, StateEvent(), _handlers)
        ui = _app.userInterface
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID, "EVE", "Open your engineering & visualization expert",
            str(Path(__file__).parent / "resources"),
        )
        _bind(definition.commandCreated, CommandCreated(), _handlers)
        qat = ui.toolbars.itemById("QAT")
        if qat and not qat.controls.itemById(COMMAND_ID):
            qat.controls.addCommand(definition)
        panel = ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        if panel:
            control = panel.controls.addCommand(definition)
            control.isPromoted = True
        _bind(ui.workspaceActivated, WorkspaceActivated(), _handlers)
        _fusion_tools = FusionTools(_app)
        _controller = Controller(_publish, fusion_tools=_fusion_tools)
        _controller.dispatch("connect")
        _controller.start_update_checks()
        _app.log(f"EVE {VERSION} loaded. Open EVE from the Quick Access toolbar or command search.")
    except Exception:
        _log_error()
        stop(context)


def stop(context):
    global _running, _controller, _palette, _want_visible, _event_pending, _fusion_tools, _pending_clipboard, _clipboard_busy
    _running = False
    _want_visible = False
    if _controller:
        _controller.close()
        _controller = None
    if _fusion_tools:
        _fusion_tools.close()
        _fusion_tools = None
    _unbind(_palette_handlers)
    _unbind(_handlers)
    if _palette and _palette.isValid:
        _palette.deleteMe()
    _palette = None
    if _app:
        ui = _app.userInterface
        qat = ui.toolbars.itemById("QAT")
        qat_control = qat.controls.itemById(COMMAND_ID) if qat else None
        if qat_control:
            qat_control.deleteMe()
        panel = ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        control = panel.controls.itemById(COMMAND_ID) if panel else None
        if control:
            control.deleteMe()
        definition = ui.commandDefinitions.itemById(COMMAND_ID)
        if definition:
            definition.deleteMe()
        _app.unregisterCustomEvent(EVENT_ID)
    _event_pending = False
    _pending_clipboard = None
    _clipboard_busy = False
