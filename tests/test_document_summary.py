from types import SimpleNamespace as Obj
import unittest
from test_fusion_bridge import Collection
from steve.document_summary import collection, design_summary, electronics_summary, cam_summary


class SummaryTests(unittest.TestCase):
    def test_large_collection_is_partial_and_resumable(self):
        result = collection(Obj(values=Collection(*range(500))), "values", lambda value: value)
        self.assertEqual(result["total"], 500)
        self.assertEqual(result["nextOffset"], 8)
        self.assertFalse(result["complete"])

    def test_unavailable_is_not_empty(self):
        missing = collection(Obj(), "values", str)
        empty = collection(Obj(values=Collection()), "values", str)
        self.assertIn("unavailable", missing)
        self.assertFalse(missing["complete"])
        self.assertTrue(empty["complete"])

    def test_profiles_are_never_evaluated(self):
        class Sketch:
            name = "Sketch"
            isFullyConstrained = False
            @property
            def profiles(self):
                raise AssertionError("Expensive profile evaluation")
        component = Obj(name="Part", sketches=Collection(Sketch()), bRepBodies=Collection(),
                        occurrences=Collection(), features=Collection())
        result = design_summary(Obj(unitsManager=Obj(defaultLengthUnits="mm"),
            allComponents=Collection(component), userParameters=Collection()))
        self.assertFalse(result["components"]["items"][0]["sketches"]["items"][0]["fullyConstrained"])

    def test_cam_does_not_read_typed_parameters(self):
        class Operation:
            name = "Mill"
            hasToolpath = True
            isToolpathValid = False
            isSuppressed = False
            @property
            def parameters(self):
                raise AssertionError("No parameter traversal")
        result = cam_summary(Obj(setups=Collection(Obj(name="Setup", operationType=0,
                                                        allOperations=Collection(Operation())))))
        self.assertFalse(result["setups"]["items"][0]["operations"]["items"][0]["isToolpathValid"])

    def test_electronics_returns_structure_and_capability_limit(self):
        board = Obj(objectType="adsk::electron::Board", name="Board", elements=Collection(Obj(name="R1")),
                    signals=Collection(), layers=Collection())
        result = electronics_summary(board)
        self.assertEqual(result["elements"]["items"], [{"name": "R1"}])
        self.assertEqual(result["designEditing"], "not_exposed")
