"""Test main-thread dispatch/lifecycle with a fake Autodesk host, not real geometry."""
import importlib.util
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as Obj
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/EVE"))


class Collection:
    def __init__(self, *values):
        self.values = list(values)
    @property
    def count(self):
        return len(self.values)
    def item(self, index):
        return self.values[index]


class Event:
    def __init__(self):
        self.handlers = []
    def add(self, handler):
        self.handlers.append(handler)
    def remove(self, handler):
        self.handlers.remove(handler)
    def fire(self, args):
        for handler in self.handlers[:]:
            handler.notify(args)


def load_bridge():
    adsk = ModuleType("adsk")
    adsk.__path__ = []
    adsk.core, adsk.fusion, adsk.cam = ModuleType("adsk.core"), ModuleType("adsk.fusion"), ModuleType("adsk.cam")
    adsk.core.CustomEventHandler = adsk.core.CommandCreatedEventHandler = adsk.core.CommandEventHandler = object
    adsk.core.DocumentEventHandler = adsk.core.ApplicationCommandEventHandler = object
    adsk.core.CommandTerminationReason = Obj(CompletedTerminationReason=1, AbortedTerminationReason=3)
    adsk.fusion.Design = Obj(cast=lambda product: product)
    modules = {"adsk": adsk, "adsk.core": adsk.core, "adsk.fusion": adsk.fusion, "adsk.cam": adsk.cam}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("eve.test_fusion_tools", ROOT / "addin/EVE/eve/fusion_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


bridge = load_bridge()


class Host:
    def __init__(self):
        self.events, self.fired = {}, []
        self.documentActivated, self.documentClosed = Event(), Event()
        self.activeProduct = Obj(productType="CAMProductType", label="before")
        self.activeDocument = Obj(name="Fixture", products=Collection(self.activeProduct))
        self.definition = Obj(commandCreated=Event(), isValid=True, execute=self.execute, deleteMe=lambda: None)
        self.userInterface = Obj(commandDefinitions=Obj(addButtonDefinition=lambda *args: self.definition),
                                 activeWorkspace=Obj(id="CAMEnvironment"), activeSelections=Collection(), activeCommand="SelectCommand")
        self.executions = 0
        self.userInterface.commandTerminated = Event()
        self.deferred = False
    def registerCustomEvent(self, name):
        self.events[name] = Event()
        return self.events[name]
    def unregisterCustomEvent(self, name):
        del self.events[name]
    def fireCustomEvent(self, name):
        self.fired.append(name)
    def pump(self):
        while self.fired:
            self.events[self.fired.pop(0)].fire(Obj())
    def execute(self):
        self.command = Obj(execute=Event(), destroy=Event())
        self.definition.commandCreated.fire(Obj(command=self.command))
        if not self.deferred:
            self.finish_command()
        return True
    def finish_command(self, termination_reason=None):
        self.executions += 1
        self.args = Obj(executeFailed=False)
        self.command.execute.fire(self.args)
        reason = termination_reason if termination_reason is not None else (3 if self.args.executeFailed else 1)
        self.command.destroy.fire(Obj(terminationReason=reason))


class FusionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.bridge = bridge.FusionTools(self.host, home=ROOT / ".cache/capture-tests" / str(uuid4()))
        self.bridge.namespaces = lambda: ["adsk.core", "adsk.fusion", "adsk.cam"]
        self.results = []
    def tearDown(self):
        self.bridge.close()
    def operation(self, code="def run(context):\n context['product'].label = 'after'\n return {'product': context['product'].productType}", cancelled=lambda: False):
        token = self.bridge.inspect_document()["document_id"]
        self.bridge.submit("fusion_execute_python", {"document_id": token, "title": "CAM operation", "code": code}, self.results.append, cancelled)

    def test_work_waits_for_main_thread_event_and_accesses_non_design_product(self):
        self.operation()
        self.assertEqual(self.host.activeProduct.label, "before")
        self.assertFalse(self.results)
        self.host.pump()
        self.assertEqual(self.host.activeProduct.label, "after")
        self.assertTrue(self.results[0]["ok"])
        self.assertTrue(self.results[0]["commandCompleted"])
        self.assertEqual(self.results[0]["result"], {"product": "CAMProductType"})
        self.assertEqual(self.host.executions, 1)

    def test_submission_from_worker_only_queues_event(self):
        worker = threading.Thread(target=lambda: self.bridge.submit("fusion_inspect_document", {}, self.results.append, lambda: False))
        worker.start(); worker.join()
        self.assertFalse(self.results)
        self.host.pump()
        self.assertEqual(self.results[0]["products"], ["CAMProductType"])

    def test_data_panel_search_then_insert_uses_existing_session_and_shared_runner(self):
        file = Obj(id="urn:fixture:bracket", name="Bracket", fileExtension="f3d", versionNumber=3)
        folder = Obj(id="folder-1", name="Parts", dataFiles=Collection(file), dataFolders=Collection())
        project = Obj(id="project-1", name="Assembly project", rootFolder=folder)
        self.host.data = Obj(activeHub=Obj(id="hub-1", name="Team"), activeProject=project,
                             activeFolder=folder, dataProjects=Collection(project),
                             findFileById=lambda file_id: file if file_id == file.id else None)
        token = self.bridge.inspect_document()["document_id"]
        snapshot = self.bridge.selection_context()["dataPanel"]
        self.assertEqual(snapshot["folder"], {"id": "folder-1", "name": "Parts"})
        self.assertIs(self.bridge.context()["data"], self.host.data)
        self.bridge.submit("fusion_query_python", {"document_id": token, "title": "Find bracket",
            "code": """def run(context):
    folder = context['data'].activeProject.rootFolder
    matches = []
    for index in range(min(folder.dataFiles.count, 20)):
        file = folder.dataFiles.item(index)
        if 'bracket' in file.name.casefold():
            matches.append({'id': file.id, 'name': file.name, 'folder': folder.name})
    return {'matches': matches, 'complete': folder.dataFiles.count <= 20}
"""}, self.results.append, lambda: False)
        self.host.pump()
        self.assertEqual(self.host.executions, 0)
        self.assertEqual(self.results[-1]["result"]["matches"][0]["id"], file.id)
        inserted = []
        def insert(data_file, transform, referenced):
            inserted.append((data_file, transform, referenced))
            return Obj(name="Bracket:1")
        design = Obj(productType="DesignProductType", rootComponent=Obj(occurrences=Obj(addByInsert=insert)),
                     unitsManager=Obj(defaultLengthUnits="mm"), allComponents=Collection(), userParameters=Collection())
        self.host.activeDocument.products = Collection(design)
        self.host.activeProduct = design
        with patch.object(bridge.adsk.core, "Matrix3D", Obj(create=lambda: "identity"), create=True), \
                patch.dict(sys.modules, {"adsk": bridge.adsk, "adsk.core": bridge.adsk.core}):
            self.operation("""def run(context):
    import adsk.core
    file = context['data'].findFileById('urn:fixture:bracket')
    occurrence = context['root'].occurrences.addByInsert(file, adsk.core.Matrix3D.create(), True)
    if occurrence is None:
        raise ValueError('Insert failed; inspect the target project before retrying')
    return {'occurrence': occurrence.name}
""")
            self.host.pump()
        self.assertTrue(self.results[-1]["ok"])
        self.assertEqual(inserted, [(file, "identity", True)])
        self.assertEqual(self.host.executions, 1)

    def test_data_panel_context_does_not_enumerate_projects_and_handles_unavailable_data(self):
        self.assertEqual(self.bridge.selection_context()["dataPanel"], {"available": False})
        class Unavailable:
            @property
            def dataProjects(self):
                raise AssertionError("Context must not enumerate projects")
            @property
            def activeProject(self):
                raise RuntimeError("Offline")
        self.host.data = Unavailable()
        self.assertEqual(self.bridge.selection_context()["dataPanel"], {"available": True})

    def test_document_switch_rejects_queued_operation(self):
        self.operation()
        self.host.activeDocument = Obj(name="Different document", products=Collection())
        self.host.pump()
        self.assertFalse(self.results[0]["ok"])
        self.assertEqual(self.host.executions, 0)

    def test_checks_target_again_when_command_executes(self):
        self.host.deferred = True
        self.operation()
        self.host.pump()
        self.host.activeDocument = Obj(name="Different document", products=Collection())
        self.host.finish_command()
        self.assertTrue(self.host.args.executeFailed)
        self.assertEqual(self.host.activeProduct.label, "before")

    def test_pinned_task_waits_for_document_then_resumes_exactly_once(self):
        original = self.host.activeDocument
        snapshot = self.bridge.message_context("send")
        waits = []
        self.bridge.on_wait = lambda message, document: waits.append(message)
        self.operation()
        other = Obj(name="Other", products=Collection())
        self.host.activeDocument = other
        self.host.pump()
        self.assertFalse(self.results)
        self.assertEqual(self.host.executions, 0)
        self.assertIsNotNone(self.bridge.waiting)
        self.assertIn("Fixture", waits[-1])
        self.assertEqual(self.bridge.message_context("steer")["document_id"], snapshot["document_id"])
        self.assertEqual(self.bridge.selection_context()["name"], "Fixture")
        self.host.activeDocument = original
        self.host.documentActivated.fire(Obj())
        self.host.pump()
        self.assertTrue(self.results[0]["ok"])
        self.assertEqual(self.host.executions, 1)
        self.host.documentActivated.fire(Obj())
        self.host.pump()
        self.assertEqual(self.host.executions, 1)

    def test_pinned_task_preserves_selection_product_and_scope_after_clicks(self):
        selected = Obj(name="Original edge", objectType="Edge", isValid=True)
        self.host.userInterface.activeSelections = Collection(Obj(entity=selected))
        original_product = self.host.activeProduct
        snapshot = self.bridge.message_context("send")
        self.host.userInterface.activeSelections = Collection(Obj(entity=Obj(name="Other edge", objectType="Edge")))
        self.host.activeProduct = Obj(productType="OtherProductType")
        self.host.userInterface.activeWorkspace = Obj(id="DifferentWorkspace")
        context = self.bridge.context()
        self.assertEqual(context["selection"], [selected])
        self.assertIs(context["product"], original_product)
        self.assertEqual(self.bridge.message_context("steer")["selection"], snapshot["selection"])
        selected.isValid = False
        self.assertEqual(self.bridge.context()["selectionInvalidCount"], 1)
        self.assertEqual(self.bridge.context()["selection"], [])

    def test_pinned_task_waits_for_user_command_without_cancelling_it(self):
        self.bridge.message_context("send")
        self.operation()
        self.host.userInterface.activeCommand = "ExtrudeCommand"
        self.host.pump()
        self.assertFalse(self.results)
        self.assertEqual(self.host.userInterface.activeCommand, "ExtrudeCommand")
        self.host.userInterface.activeCommand = "SelectCommand"
        self.host.userInterface.commandTerminated.fire(Obj())
        self.host.pump()
        self.assertTrue(self.results[0]["ok"])

    def test_tab_change_between_command_queue_and_execute_defers_before_code_runs(self):
        original = self.host.activeDocument
        self.bridge.message_context("send")
        self.host.deferred = True
        self.operation()
        self.host.pump()
        self.host.activeDocument = Obj(name="Other", products=Collection())
        self.host.finish_command()
        self.assertFalse(self.results)
        self.assertEqual(self.host.activeProduct.label, "before")
        self.assertIsNotNone(self.bridge.waiting)
        self.host.activeDocument = original
        self.host.documentActivated.fire(Obj())
        self.host.pump()
        self.host.finish_command()
        self.assertTrue(self.results[0]["ok"])
        self.assertEqual(self.host.activeProduct.label, "after")

    def test_waiting_work_can_be_cancelled_and_closed_target_is_not_replaced(self):
        original = self.host.activeDocument
        original.isValid = True
        self.bridge.message_context("send")
        cancelled = [False]
        self.operation(cancelled=lambda: cancelled[0])
        self.host.activeDocument = Obj(name="Other", products=Collection())
        self.host.pump()
        cancelled[0] = True
        self.bridge.wake()
        self.host.pump()
        self.assertEqual(self.results[-1]["errorCode"], "cancelled")
        cancelled[0] = False
        self.operation()
        self.host.pump()
        original.isValid = False
        self.host.documentClosed.fire(Obj())
        self.host.pump()
        self.assertEqual(self.results[-1]["errorCode"], "target_document_closed")
        self.assertEqual(self.host.executions, 0)

    def test_application_created_document_transfers_pin(self):
        self.bridge.message_context("send")
        old_id = self.bridge.document_id
        replacement = Obj(name="Created by EVE", products=Collection(self.host.activeProduct))
        self.host.documents = Obj(add=lambda: setattr(self.host, "activeDocument", replacement))
        self.bridge.submit("fusion_execute_python", {"document_id": old_id, "title": "Create document",
            "execution_mode": "application", "code": "def run(context):\n context['app'].documents.add()\n return {'created': True}"}, self.results.append, lambda: False)
        self.host.pump()
        self.assertTrue(self.results[-1]["ok"])
        self.assertNotEqual(self.bridge.document_id, old_id)
        self.assertEqual(self.bridge.selection_context()["name"], "Created by EVE")

    def test_fusion_abort_after_python_success_is_reported_as_failure(self):
        self.host.deferred = True
        self.operation()
        self.host.pump()
        self.assertFalse(self.host.command.isExecutedWhenPreEmpted)
        self.host.finish_command(termination_reason=3)
        self.assertEqual(self.host.activeProduct.label, "after")
        self.assertFalse(self.results[0]["ok"])
        self.assertFalse(self.results[0]["commandCompleted"])
        self.assertIn("Fusion did not complete", self.results[0]["error"])

    def test_application_mode_runs_without_command_and_reinspects_new_document(self):
        old_token = self.bridge.inspect_document()["document_id"]
        replacement = Obj(name="New document", products=Collection(self.host.activeProduct))
        self.host.documents = Obj(add=lambda: setattr(self.host, "activeDocument", replacement))
        self.bridge.submit("fusion_execute_python", {
            "document_id": old_token, "title": "Create document", "execution_mode": "application",
            "code": "def run(context):\n context['app'].documents.add()\n return {'created': True}"},
            self.results.append, lambda: False)
        self.assertFalse(self.results)
        self.host.pump()
        self.assertEqual(self.host.executions, 0)
        self.assertTrue(self.results[0]["ok"])
        self.assertFalse(self.results[0]["undoGrouped"])
        self.assertEqual(self.results[0]["document"]["name"], "New document")
        self.assertNotEqual(self.results[0]["document"]["document_id"], old_token)

    def test_query_uses_shared_runner_without_starting_a_command(self):
        token = self.bridge.inspect_document()["document_id"]
        self.host.activeProduct.setups = [Obj(name="Setup 1", machine="Fixture mill")]
        self.bridge.submit("fusion_query_python", {
            "document_id": token, "title": "List setup machines",
            "code": "def run(context):\n print('Read CAM setups')\n return [{'name': s.name, 'machine': s.machine} for s in context['products']['CAMProductType'].setups]"},
            self.results.append, lambda: False)
        self.assertFalse(self.results)
        self.host.pump()
        self.assertEqual(self.host.executions, 0)
        self.assertTrue(self.results[0]["ok"])
        self.assertEqual(self.results[0]["executionMode"], "query")
        self.assertEqual(self.results[0]["result"], [{"name": "Setup 1", "machine": "Fixture mill"}])
        self.assertEqual(self.results[0]["output"], "Read CAM setups\n")

    def test_cam_crash_guard_covers_query_command_and_application_modes(self):
        class Parameter:
            name = "probe_geometry"
            reads = 0
            @property
            def value(self):
                self.reads += 1
                raise AssertionError("Native getter must never be entered")
        parameter = Parameter()
        original = Parameter.value
        self.host.activeProduct.parameter = parameter
        token = self.bridge.inspect_document()["document_id"]
        with patch.object(bridge.adsk.cam, "CAMParameter", Parameter, create=True):
            for tool, mode in (("fusion_query_python", None), ("fusion_execute_python", "command"),
                               ("fusion_execute_python", "application")):
                arguments = {"document_id": token, "title": "Probe fixture",
                             "code": "def run(context):\n return context['product'].parameter.value"}
                if mode:
                    arguments["execution_mode"] = mode
                self.bridge.submit(tool, arguments, self.results.append, lambda: False)
                self.host.pump()
                self.assertFalse(self.results[-1]["ok"])
                self.assertEqual(self.results[-1]["errorCode"], "unsafe_cam_probe_value")
                self.assertEqual(parameter.reads, 0)
                self.assertIs(Parameter.value, original)

    def test_query_rejects_stale_target_and_returns_script_errors(self):
        token = self.bridge.inspect_document()["document_id"]
        arguments = {"document_id": token, "title": "Query", "code": "def run(context):\n raise ValueError('query failed')"}
        self.bridge.submit("fusion_query_python", arguments, self.results.append, lambda: False)
        self.host.pump()
        self.assertIn("query failed", self.results[-1]["error"])
        self.assertEqual(self.results[-1]["trace"], ["line 2 in run"])
        self.bridge.submit("fusion_query_python", arguments, self.results.append, lambda: False)
        self.host.activeDocument = Obj(name="Different", products=Collection())
        self.host.pump()
        self.assertIn("active document changed", self.results[-1]["error"])
        self.assertEqual(self.host.executions, 0)

    def test_oversized_return_does_not_abort_successful_modeling(self):
        self.operation("def run(context):\n context['product'].label = 'created'\n return 'x' * 30000")
        self.host.pump()
        self.assertEqual(self.host.activeProduct.label, "created")
        self.assertFalse(self.host.args.executeFailed)
        self.assertTrue(self.results[0]["ok"])
        self.assertTrue(self.results[0]["resultTruncated"])

    def test_selection_snapshot_is_bounded_and_keeps_resolvable_references(self):
        entity = Obj(objectType="adsk::fusion::BRepEdge", name="Edge", entityToken="edge-token", body=Obj(name="Bracket"), assemblyContext=Obj(fullPathName="Assembly:1+Bracket:1"))
        self.host.userInterface.activeSelections = Collection(*[Obj(entity=entity) for _ in range(20)])
        snapshot = self.bridge.selection_context()
        self.assertEqual(snapshot["selectionCount"], 20)
        self.assertTrue(snapshot["selectionTruncated"])
        self.assertEqual(snapshot["selection"][0]["entityToken"], "edge-token")
        self.assertEqual(snapshot["selection"][0]["body"], "Bracket")
        self.assertIs(self.bridge.context()["selection"][0], entity)
        self.host.userInterface.activeSelections = Collection()
        self.assertEqual(snapshot["selectionCount"], 20)
        self.assertEqual(self.bridge.selection_context()["selection"], [])

    def test_capture_runs_on_main_thread_preserves_size_ratio_and_removes_temp_file(self):
        captures = []
        def save(path, width, height):
            captures.append((path, width, height))
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            return True
        self.host.activeViewport = Obj(width=2400, height=1200, refresh=lambda: True, saveAsImageFile=save)
        token = self.bridge.selection_context()["document_id"]
        self.bridge.submit("fusion_capture_viewport", {"document_id": token}, self.results.append, lambda: False)
        self.assertFalse(captures)
        self.host.pump()
        self.assertEqual(captures[0][1:], (1280, 640))
        self.assertTrue(self.results[0]["imageUrl"].startswith("data:image/png;base64,"))
        self.assertFalse(Path(captures[0][0]).exists())
        self.assertEqual(self.host.executions, 0)

    def test_capture_missing_viewport_has_actionable_error(self):
        self.host.activeViewport = None
        token = self.bridge.selection_context()["document_id"]
        self.bridge.submit("fusion_capture_viewport", {"document_id": token}, self.results.append, lambda: False)
        self.host.pump()
        self.assertEqual(self.results[0]["errorCode"], "viewport_unavailable")
        self.assertIn("open the intended document", self.results[0]["recovery"])

    def test_application_mode_keeps_target_and_cancellation_checks(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                token = self.bridge.inspect_document()["document_id"]
                self.bridge.submit("fusion_execute_python", {
                    "document_id": token, "title": "Application operation", "execution_mode": "application",
                    "code": "def run(context):\n context['product'].label = 'should not run'"},
                    self.results.append, lambda: cancel)
                if not cancel:
                    self.host.activeDocument = Obj(name="Switched", products=Collection(self.host.activeProduct))
                self.host.pump()
                self.assertFalse(self.results[-1]["ok"])
                self.assertEqual(self.host.activeProduct.label, "before")

    def test_cancellation_and_active_native_command_do_not_execute(self):
        self.operation(cancelled=lambda: True)
        self.host.pump()
        self.assertEqual(self.host.executions, 0)
        self.host.userInterface.activeCommand = "NativeEditCommand"
        self.operation()
        self.host.pump()
        self.assertEqual(self.host.executions, 0)
        self.assertIn("active Fusion command", self.results[-1]["error"])

    def test_script_failure_requests_transaction_abort_and_reports_error(self):
        self.operation("def run(context):\n raise ValueError('fixture failure')")
        self.host.pump()
        self.assertTrue(self.host.args.executeFailed)
        self.assertTrue(self.results[0]["transactionAborted"])
        self.assertIn("fixture failure", self.results[0]["error"])

    def test_api_help_discovers_installed_members_without_executing_them(self):
        api = Obj(CAM=type("CAM", (), {"createSetup": lambda self: None}))
        with patch.object(bridge.importlib, "import_module", return_value=api):
            self.bridge.submit("fusion_api_help", {"path": "adsk.cam.CAM"}, self.results.append, lambda: False)
            self.host.pump()
        self.assertIn("createSetup", self.results[0]["members"])

    def test_shutdown_cancels_pending_operations(self):
        self.operation()
        self.bridge.close()
        self.assertFalse(self.results[0]["ok"])
        self.assertEqual(self.host.executions, 0)
        # Avoid a second close: Fusion entrypoint owns this lifecycle once.
        self.bridge.close = lambda: None


if __name__ == "__main__":
    unittest.main()
