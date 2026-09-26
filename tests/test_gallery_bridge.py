import json
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch
from test_clipboard_bridge import load_entry


class GalleryBridgeTests(unittest.TestCase):
    def setUp(self):
        self.entry = load_entry()
        self.controller = Obj(gallery_request=Mock(return_value={'image': {'url': 'data:image/png;base64,fixture'}}),
                              debug=Obj(record=Mock()), snapshot=lambda: {'status': 'Working'})
        self.entry._controller = self.controller
        self.entry._running = True
        self.entry._app = Obj(fireCustomEvent=Mock(), log=Mock())
        self.entry._palette = Obj(isValid=True, sendInfoToHTML=Mock())

    def test_request_uses_worker_and_pixels_are_only_delivered_by_custom_event(self):
        args = Obj(action='gallery', data=json.dumps({'requestId': 'g1', 'action': 'asset'}))
        with patch.object(self.entry.threading, 'Thread') as thread:
            self.entry.HTMLMessage().notify(args)
            thread.return_value.start.assert_called_once()
        self.controller.gallery_request.assert_not_called()
        self.assertTrue(json.loads(args.returnData)['pending'])
        self.entry._gallery_request({'requestId': 'g1', 'action': 'asset'}, self.controller)
        self.entry._palette.sendInfoToHTML.assert_not_called()
        self.assertNotIn('base64', json.dumps(self.entry._pending_state))
        self.entry.StateEvent().notify(None)
        calls = self.entry._palette.sendInfoToHTML.call_args_list
        self.assertEqual([call.args[0] for call in calls], ['state', 'gallery'])
        self.assertFalse(self.entry._gallery_busy)
        self.entry.StateEvent().notify(None)
        self.assertEqual(sum(c.args[0] == 'gallery' for c in self.entry._palette.sendInfoToHTML.call_args_list), 1)

    def test_stale_controller_result_is_discarded(self):
        self.entry._controller = object()
        self.entry._gallery_request({'requestId': 'old'}, self.controller)
        self.assertIsNone(self.entry._pending_gallery)

    def test_updater_handoff_waits_for_gallery_worker(self):
        self.entry._pending_state = {'updateInstallReady': True}
        self.entry._gallery_busy = True
        self.entry._fusion_tools = Obj(command_state=Mock(return_value={'activeCommand': 'SelectCommand'}))
        self.controller.check_update_failure = Mock()
        self.controller.take_prepared_update = Mock(return_value=None)
        self.entry.StateEvent().notify(None)
        self.controller.take_prepared_update.assert_not_called()
        self.entry._gallery_request({'requestId': 'g1'}, self.controller)
        self.entry._pending_state = {'updateInstallReady': True}
        self.entry.StateEvent().notify(None)
        self.controller.take_prepared_update.assert_called_once()

    def test_concurrent_or_invalid_request_is_rejected_and_errors_are_returned(self):
        self.entry._gallery_busy = True
        for data in [{'requestId': 'g1'}, {'requestId': ''}, {'path': 'arbitrary'}]:
            args = Obj(action='gallery', data=json.dumps(data))
            with patch.object(self.entry.threading, 'Thread') as thread:
                self.entry.HTMLMessage().notify(args)
                thread.assert_not_called()
            self.assertFalse(json.loads(args.returnData)['ok'])
        self.controller.gallery_request.side_effect = ValueError('fixture failure')
        self.entry._gallery_request({'requestId': 'g1'}, self.controller)
        self.entry.StateEvent().notify(None)
        result = json.loads(self.entry._palette.sendInfoToHTML.call_args_list[-1].args[1])
        self.assertEqual(result['error'], 'fixture failure')
        self.assertFalse(self.entry._gallery_busy)
