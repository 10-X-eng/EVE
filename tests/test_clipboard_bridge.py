"""Clipboard completion stays outside streamed state and uses Fusion's main event."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))


def load_entry():
    package = ModuleType("clipboard_test_addin")
    package.__path__ = [str(ROOT / "addin/STEVE")]
    adsk = ModuleType("adsk")
    core = ModuleType("adsk.core")
    adsk.core = core
    for name in ("CustomEventHandler", "HTMLEventHandler", "UserInterfaceGeneralEventHandler",
                 "CommandEventHandler", "CommandCreatedEventHandler", "WorkspaceEventHandler"):
        setattr(core, name, object)
    core.HTMLEventArgs = Obj(cast=lambda args: args)
    fake_tools = ModuleType("clipboard_test_addin.steve.fusion_tools")
    fake_tools.FusionTools = object
    modules = {"clipboard_test_addin": package, "adsk": adsk, "adsk.core": core,
               "clipboard_test_addin.steve.fusion_tools": fake_tools}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("clipboard_test_addin.STEVE", ROOT / "addin/STEVE/STEVE.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
    return entry


class ClipboardBridgeTests(unittest.TestCase):
    def setUp(self):
        self.entry = load_entry()
        self.controller = Obj(debug=Obj(record=Mock()), snapshot=lambda: {"status": "Working"})
        self.entry._controller = self.controller
        self.entry._running = True
        self.entry._app = Obj(fireCustomEvent=Mock())
        self.entry._palette = Obj(isValid=True, sendInfoToHTML=Mock())

    def test_pixels_are_delivered_separately_on_main_event(self):
        image = {"name": "fixture", "url": "data:image/png;base64,fixture"}
        with patch.object(self.entry, "read_clipboard_image", return_value=image):
            self.entry._read_pasted_image("paste-1", self.controller)
        self.entry._palette.sendInfoToHTML.assert_not_called()
        self.assertNotIn("image", self.entry._pending_state)
        self.entry.StateEvent().notify(None)
        calls = self.entry._palette.sendInfoToHTML.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["state", "clipboardImage"])
        self.assertNotIn("base64", calls[0].args[1])
        self.entry.StateEvent().notify(None)
        self.assertEqual(sum(call.args[0] == "clipboardImage" for call in self.entry._palette.sendInfoToHTML.call_args_list), 1)

    def test_stopped_or_replaced_controller_cannot_publish_paste(self):
        with patch.object(self.entry, "read_clipboard_image", return_value=None):
            self.entry._controller = object()
            self.entry._read_pasted_image("old-paste", self.controller)
        self.assertIsNone(self.entry._pending_clipboard)
        self.entry._app.fireCustomEvent.assert_not_called()

    def test_invalid_request_and_concurrent_paste_are_rejected(self):
        self.entry._app.log = Mock()
        for payload in ('{"path":"anything"}', '{"requestId":"paste-1"}'):
            self.entry._clipboard_busy = True
            args = Obj(action="clipboardImage", data=payload, returnData=None)
            with patch.object(self.entry.threading, "Thread") as thread:
                self.entry.HTMLMessage().notify(args)
                thread.assert_not_called()
            self.assertIn('"ok": false', args.returnData)


if __name__ == "__main__":
    unittest.main()
