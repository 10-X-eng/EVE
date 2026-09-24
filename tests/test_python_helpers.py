from types import SimpleNamespace as Obj
import unittest
from test_fusion_bridge import Collection
from steve.python_helpers import FusionHelpers, helper_help
from steve.tool_protocol import validate_call


class HelperTests(unittest.TestCase):
    def test_invalid_selection_keeps_original_indices(self):
        original = Obj(isValid=False)
        second = Obj(isValid=True, objectType='Edge')
        helper = FusionHelpers({}, [original, second])
        with self.assertRaisesRegex(RuntimeError, 'no longer valid'):
            helper.selected(0)
        self.assertIs(helper.selected(1, 'Edge'), second)
        with self.assertRaisesRegex(RuntimeError, 'objectType'):
            helper.selected(1, 'Face')

    def test_token_resolution_does_not_choose_first_ambiguous_match(self):
        helper = FusionHelpers({'design': Obj(findEntityByToken=lambda token: [Obj(), Obj()])}, [])
        with self.assertRaisesRegex(RuntimeError, 'multiple'):
            helper.entity('token')
        helper = FusionHelpers({'design': Obj(findEntityByToken=lambda token: [])}, [])
        with self.assertRaisesRegex(RuntimeError, 'zero'):
            helper.entity('token')

    def test_units_are_validated_before_evaluation(self):
        calls = []
        units = Obj(isValidExpression=lambda expr, kind: expr == '8 mm' and kind == 'mm',
                    evaluateExpression=lambda expr, kind: calls.append(expr) or 0.8)
        helper = FusionHelpers({'units': units}, [])
        self.assertEqual(helper.evaluate('8 mm', 'mm'), 0.8)
        with self.assertRaises(ValueError):
            helper.evaluate('8 kg', 'mm')
        self.assertEqual(calls, ['8 mm'])
        with self.assertRaisesRegex(ValueError, 'Design units'):
            FusionHelpers({}, []).evaluate('8 mm', 'mm')

    def test_sparse_filtered_page_resumes_after_scanned_items(self):
        helper = FusionHelpers({}, [])
        values = Collection(*range(1000))
        first = helper.page(values, lambda x: x, where=lambda x: x % 50 == 0, scan_limit=100)
        second = helper.page(values, lambda x: x, offset=first['nextOffset'], where=lambda x: x % 50 == 0, scan_limit=100)
        self.assertEqual(first['items'], [0, 50])
        self.assertEqual(second['items'], [100, 150])
        self.assertFalse(first['complete'])
        self.assertEqual(first['scanned'], 100)
        self.assertEqual(helper.page(Collection(), str)['nextOffset'], None)
        self.assertEqual(helper.page(values, str, offset=2000)['scanned'], 0)

    def test_helpers_are_discoverable_without_opening_private_modules(self):
        validate_call('fusion_api_help', {'path': 'steve.helpers'})
        self.assertIn('evaluate', helper_help()['members'])
        with self.assertRaises(ValueError):
            validate_call('fusion_api_help', {'path': 'steve.transport'})
