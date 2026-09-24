"""Main-thread execution bridge for the full installed Autodesk Python API."""
import importlib
import copy
import base64
import inspect
import json
from pathlib import Path
import pkgutil
import queue
import time
from uuid import uuid4

import adsk.core
import adsk.fusion
import adsk.cam

from .python_runner import run_python, bounded_result
from .document_summary import design_summary, cam_summary, electronics_summary
from .verification import Checks, snapshot, report
from .python_helpers import FusionHelpers, helper_help
from .viewport import temporary_camera
from .cam_guard import protect_cam_values
from .dfm import DfmStore, DfmChecks, guide as dfm_guide, native as native_body
from .dfm_geometry import DfmGeometry
from .rmfg_snapshot import export_snapshot
from .tool_protocol import API_GUIDANCE, ToolError, tool_failure
from .transport import data_home

EVENT_ID = "10X_STEVE_Tool"
COMMAND_ID = "10X_STEVE_ExecutePython"


def items(collection, limit=100):
    return [collection.item(index) for index in range(min(collection.count, limit))]


def optional_property(obj, name):
    try:
        return getattr(obj, name, None)
    except (AttributeError, RuntimeError):
        return None


class EventHandler(adsk.core.CustomEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        self.owner.drain()


class DocumentWake(adsk.core.DocumentEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        self.owner.wake()


class CommandWake(adsk.core.ApplicationCommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        self.owner.wake()


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        command = args.command
        command.isAutoExecute = True
        command.isExecutedWhenPreEmpted = False
        self.owner.bind(command.execute, ExecuteHandler(self.owner), self.owner.command_handlers)
        self.owner.bind(command.destroy, DestroyHandler(self.owner), self.owner.command_handlers)


class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        owner = self.owner
        job = owner.active
        if job is None:
            args.executeFailed = True
            return
        if (owner.task and not job["cancelled"]() and owner.document is not None
                and owner.app.activeDocument != owner.document
                and optional_property(owner.document, "isValid") is not False):
            # The tab can change after execute() queues the command but before
            # this callback. No generated code has run, so it is safe to defer.
            job["deferredBeforeExecution"] = True
            args.executeFailed = True
            args.executeFailedMessage = "Waiting for the task document."
            return
        try:
            owner.check_target(job)
            job["result"] = owner.run_script(job)
        except Exception as exc:
            job["result"] = tool_failure(exc)
        if not job["result"]["ok"]:
            args.executeFailed = True
            args.executeFailedMessage = job["result"]["error"][:500]
            job["result"]["transactionAborted"] = True


class DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        owner = self.owner
        job, owner.active = owner.active, None
        # Command owns the event objects until destroy returns; keep handlers alive
        # in this local list during callbacks, then release them.
        handlers, owner.command_handlers = owner.command_handlers, []
        if job:
            if job.pop("deferredBeforeExecution", False):
                owner.waiting = job
                owner.on_wait("Waiting for " + (owner.task["snapshot"]["name"] or "the task document"), owner.task_label())
                return
            result = job.get("result") or tool_failure(ToolError("cancelled", "Fusion cancelled the command before execution."))
            result["executionMode"] = "command"
            completed = args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason
            result["commandCompleted"] = completed
            if result["ok"] and not completed:
                result.update(tool_failure(ToolError("command_incomplete", "Python returned, but Fusion did not complete the command."), execution_started=True))
            try:
                result["document"] = owner.inspect_document()
            except Exception as exc:
                result["inspectionError"] = str(exc)
            owner.verify(job, result)
            owner.finish(job, result)


class FusionTools:
    def __init__(self, app, home=None):
        self.app = app
        self.queue = queue.Queue()
        self.active = None
        self.waiting = None
        self.task = None
        self.saved_tasks = {}
        self.on_wait = lambda waiting, document: None
        self.closed = False
        self.handlers = []
        self.command_handlers = []
        self.document = None
        self.document_id = None
        self.debug = None
        self.dfm = DfmStore(home or data_home())
        self.capture_folder = Path(home or data_home()) / "captures"
        self.bind(app.registerCustomEvent(EVENT_ID), EventHandler(self), self.handlers)
        self.definition = app.userInterface.commandDefinitions.addButtonDefinition(
            COMMAND_ID, "STEVE operation", "Run a Python operation requested through STEVE")
        self.bind(self.definition.commandCreated, CreatedHandler(self), self.handlers)
        for event in (app.documentActivated, app.documentClosed):
            self.bind(event, DocumentWake(self), self.handlers)
        self.bind(app.userInterface.commandTerminated, CommandWake(self), self.handlers)

    def command_state(self):
        ui = self.app.userInterface
        command = ui.activeCommand
        workspace = optional_property(ui, "activeWorkspace")
        product = self.task["product"] if self.task else self.app.activeProduct
        workspace_id = optional_property(workspace, "id")
        product_type = optional_property(product, "productType")
        execution_allowed = command in ("SelectCommand", COMMAND_ID)
        # GROUP is Electronics' default selection command, not an idle SelectCommand.
        # Only the observed schematic state is verified; do not exempt editing commands
        # or let a workspace switch authorize access to a different pinned product.
        schematic_selection = (command == "Electron::Group"
                               and workspace_id == "SchEditorEnvironement"
                               and product_type == "SchematicProductType"
                               and self.app.activeProduct == product)
        return {"activeCommand": command, "workspace": workspace_id,
                "product": product_type, "executionAllowed": execution_allowed,
                "readAllowed": execution_allowed or schematic_selection}

    def check_command(self, tool):
        state = self.command_state()
        if tool in ("fusion_query_python", "fusion_capture_viewport", "fusion_dfm_plan", "fusion_dfm_check", "fusion_rmfg"):
            return state["readAllowed"]
        if state["readAllowed"] and not state["executionAllowed"]:
            raise ToolError("electronics_selection_read_only",
                            "Electronics GROUP is the normal selection mode. STEVE can inspect "
                            "and query this schematic, but cannot launch a modifying operation "
                            "in this command state. No code was executed.")
        return state["executionAllowed"]

    def wait_for(self, job, reason):
        self.waiting = job
        state = self.command_state()
        if self.debug:
            self.debug.record("fusion.queued", tool=job["tool"], reason=reason,
                              elapsedSeconds=round(time.monotonic() - job["queuedAt"], 1), **state)
        self.on_wait(reason, self.task_label())

    def wake(self):
        # Safe from the controller worker as well as Fusion event callbacks.
        if not self.closed:
            self.app.fireCustomEvent(EVENT_ID)

    def task_label(self):
        return {"id": self.document_id, "name": self.task["snapshot"]["name"]} if self.task else None

    def message_context(self, action):
        """Called on the Fusion thread only after the controller accepts Send."""
        if action.startswith("resume:"):
            key = action.partition(":")[2]
            saved = self.saved_tasks.get(key)
            if not saved or (saved[1] is not None and optional_property(saved[1], "isValid") is False):
                raise ToolError("target_document_closed", "The job's original document is no longer available. Create a new job on the intended document.")
            self.task, self.document, self.document_id = saved
        if action == "send":
            self.task = None
            snapshot = self.selection_context()
            self.task = {"snapshot": snapshot, "product": self.app.activeProduct,
                         "selection": [entry.entity for entry in items(self.app.userInterface.activeSelections)]}
            snapshot["task_key"] = str(uuid4())
            self.saved_tasks[snapshot["task_key"]] = (self.task, self.document, self.document_id)
            while len(self.saved_tasks) > 64:
                self.saved_tasks.pop(next(iter(self.saved_tasks)))
        if not self.task:
            raise ToolError("inactive_request", "There is no Fusion task to steer.")
        return copy.deepcopy({**self.task["snapshot"], "targetPinned": True})

    @staticmethod
    def bind(event, handler, collection):
        event.add(handler)
        collection.append((event, handler))

    def run_script(self, job):
        context = self.context()
        dfm = None
        if job['tool'] == 'fusion_dfm_check':
            body, key, plan = self.dfm_target(job['arguments'], context)
            index = job['arguments']['stage']
            if not plan or index >= len(plan['stages']):
                raise ToolError('dfm_plan_required', 'No saved manufacturing plan at that stage index.')
            dfm = DfmChecks(body, plan['stages'][index])
            dfm.measurements = DfmGeometry(body, self.app, adsk.core, adsk.cam, job['cancelled'])
            context['dfm'] = dfm
        if job["tool"] == "fusion_execute_python":
            job["before"] = snapshot(context["design"])
            job["checks"] = Checks()
            context["verification"] = job["checks"]
        script_id = str(uuid4())
        def record(event, **details):
            if self.debug:
                self.debug.record(event, scriptId=script_id, title=job["arguments"]["title"], **details)
        record("python.started", code=job["arguments"]["code"], crashGuard="cam-probe-v1")
        with protect_cam_values(getattr(adsk.cam, "CAMParameter", None), record):
            result = run_python(job["arguments"]["code"], context, job["cancelled"],
                                diagnostic=record if self.debug and self.debug.enabled else None)
        if dfm is not None:
            result['dfm'] = dfm.report(result['ok'])
        if (self.task and job["arguments"].get("execution_mode") == "application"
                and self.app.activeDocument != self.document):
            # An application-mode script can intentionally create/open a document.
            # No UI event pumping occurs during execution; capture its resulting target.
            key = self.task["snapshot"]["task_key"]
            self.message_context("send")
            self.saved_tasks.pop(self.task["snapshot"]["task_key"], None)
            self.task["snapshot"]["task_key"] = key
            self.saved_tasks[key] = (self.task, self.document, self.document_id)
            self.on_wait("", self.task_label())
        record("python.completed", ok=result["ok"])
        return result

    def dfm_target(self, arguments, context=None):
        if not self.dfm.enabled:
            raise ToolError('dfm_disabled', 'Enable DFM in STEVE before using DFM tools.')
        context = context or self.context()
        design = context['design']
        if design is None:
            raise ToolError('dfm_target_unavailable', 'DFM requires a Design product and a BRepBody.')
        found = design.findEntityByToken(arguments['part_token'])
        body = adsk.fusion.BRepBody.cast(found[0]) if len(found) == 1 else None
        if body is None or not body.isValid:
            raise ToolError('dfm_target_unavailable', 'The body token is invalid, ambiguous or no longer available.')
        body = native_body(body)
        data_file = optional_property(context['document'], 'dataFile')
        file_id = optional_property(data_file, 'id')
        key = file_id if file_id else 'session:' + str(self.document_id)
        return body, key, self.dfm.plan(key, body, design)

    def dfm_plan(self, arguments):
        context = self.context()
        body, key, plan = self.dfm_target(arguments, context)
        if 'stages' in arguments:
            self.dfm.save_plan(key, body, context['design'], arguments['stages'])
            plan = self.dfm.plan(key, body, context['design'])
        return {'ok': True, 'body': body.name, 'partToken': body.entityToken,
                'plan': plan, 'persistence': 'session' if key.startswith('session:') else 'local',
                'scope': 'Native body definition. Occurrence placement, assembly context and build orientation require explicit checks.'}

    def rmfg_snapshot(self, arguments):
        context = self.context()
        body, key, plan = self.dfm_target(arguments, context)
        if not plan or not any(stage['process'] == 'sheet_metal' for stage in plan['stages']):
            raise ToolError('dfm_plan_required', 'RMFG checks require a saved sheet_metal stage for the intended body.')
        if arguments['action'] == 'prepare':
            return export_snapshot(body, context['design'], key)
        binding = arguments['_binding']
        resolved = context['design'].findEntityByToken(binding['partToken'])
        if key != binding['documentKey'] or len(resolved) != 1 or native_body(resolved[0]) != body:
            raise ToolError('dfm_target_unavailable', 'This RMFG job belongs to a different or unavailable part.')
        return {'ok': True, 'snapshotMatches': body.revisionId == binding['revision']}

    def verify(self, job, result):
        if "before" not in job:
            return
        try:
            healthy = adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            result["verification"] = report(job["before"], snapshot(self.context()["design"]),
                job["checks"].results, result["ok"], healthy)
        except (AttributeError, RuntimeError) as exc:
            result["verification"] = {"status": "incomplete", "unavailable": str(exc)[:200],
                                      "checks": job["checks"].results}

    def submit(self, tool, arguments, complete, cancelled):
        # Called from the transport reader. fireCustomEvent is the only Fusion
        # API call permitted here. All document/API access occurs in drain().
        if self.closed:
            complete(tool_failure(ToolError("cancelled", "STEVE is shutting down.")))
            return
        job = {"tool": tool, "arguments": arguments, "complete": complete, "cancelled": cancelled,
               "queuedAt": time.monotonic()}
        self.queue.put(job)
        try:
            self.app.fireCustomEvent(EVENT_ID)
        except Exception:
            job["cancelled"] = lambda: True
            raise

    def finish(self, job, result):
        if job.get("finished"):
            return
        job["finished"] = True
        try:
            job["complete"](result)
        finally:
            if not self.closed and not self.queue.empty():
                self.app.fireCustomEvent(EVENT_ID)

    def context(self):
        document = self.document if self.task else self.app.activeDocument
        if document is not None and optional_property(document, "isValid") is False:
            raise ToolError("target_document_closed", "The task's document is no longer available.")
        products = {product.productType: product for product in items(document.products)} if document else {}
        design = adsk.fusion.Design.cast(products.get("DesignProductType"))
        selection = self.task["selection"] if self.task else [entry.entity for entry in items(self.app.userInterface.activeSelections)]
        valid_selection = [entity for entity in selection if optional_property(entity, "isValid") is not False]
        context = {"app": self.app, "data": optional_property(self.app, "data"),
                "targetPinned": bool(self.task), "dataPanel": copy.deepcopy(self.task["snapshot"]["dataPanel"]) if self.task else self.data_context(),
                "ui": self.app.userInterface, "document": document,
                "product": self.task["product"] if self.task else self.app.activeProduct,
                "products": products, "design": design,
                "root": design.rootComponent if design else None,
                "units": design.unitsManager if design else None,
                "selection": valid_selection, "selectionInvalidCount": len(selection) - len(valid_selection),
                "selectionCount": self.task["snapshot"]["selectionCount"] if self.task else self.app.userInterface.activeSelections.count}
        context["helpers"] = FusionHelpers(context, selection)
        return context

    def selection_context(self):
        """Capture a small, serializable snapshot on Fusion's main thread at Send."""
        if self.task:
            return copy.deepcopy({**self.task["snapshot"], "targetPinned": True})
        document = self.app.activeDocument
        if self.document_id is None or document != self.document:
            self.document, self.document_id = document, str(uuid4())
        ui = self.app.userInterface
        selections = ui.activeSelections
        selected, size = [], 0
        for index, selection in enumerate(items(selections, 12)):
            entity = selection.entity
            entry = {"index": index, "type": entity.objectType, "name": str(optional_property(entity, "name") or "")[:200]}
            for field, source, attribute in (("entityToken", entity, "entityToken"),
                    ("body", optional_property(entity, "body"), "name"),
                    ("occurrence", optional_property(entity, "assemblyContext"), "fullPathName")):
                try:
                    value = getattr(source, attribute, None)
                    if isinstance(value, str) and len(value) <= (2048 if field == "entityToken" else 200):
                        entry[field] = value
                except (AttributeError, RuntimeError):
                    pass
            size += len(json.dumps(entry, ensure_ascii=False))
            if size > 10000:
                break
            selected.append(entry)
        workspace = ui.activeWorkspace
        product = self.app.activeProduct
        return {"document_id": self.document_id, "name": document.name if document else None,
                "workspace": workspace.id if workspace else None,
                "activeProduct": product.productType if product else None,
                "selectionCount": selections.count, "selection": selected,
                "selectionTruncated": len(selected) < selections.count,
                "dataPanel": self.data_context()}

    def data_context(self):
        """Identify the current Data Panel scope without enumerating cloud libraries."""
        data = optional_property(self.app, "data")
        result = {"available": data is not None}
        if data is not None:
            for label, attribute in (("hub", "activeHub"), ("project", "activeProject"),
                                     ("folder", "activeFolder")):
                value = optional_property(data, attribute)
                if value is not None:
                    result[label] = {"name": str(optional_property(value, "name") or "")[:200],
                                     "id": str(optional_property(value, "id") or "")[:2048]}
        return result

    def capture_viewport(self, job):
        self.check_target(job)
        if not self.check_command("fusion_capture_viewport"):
            raise ToolError("active_command", "Finish the active Fusion command before capturing its viewport.")
        viewport = self.app.activeViewport
        if viewport is None or self.app.activeDocument is None:
            raise ToolError("viewport_unavailable", "There is no active document viewport to capture.")
        scale = min(1.0, 1280 / max(1, viewport.width, viewport.height))
        width, height = max(1, round(viewport.width * scale)), max(1, round(viewport.height * scale))
        self.capture_folder.mkdir(parents=True, exist_ok=True)
        path = self.capture_folder / (str(uuid4()) + ".png")
        try:
            with temporary_camera(viewport, self.context(), job["arguments"], adsk.core, job["cancelled"]):
                viewport.refresh()
                if not viewport.saveAsImageFile(str(path), width, height):
                    raise ToolError("viewport_capture_failed", "Fusion could not render the viewport image.")
                if path.stat().st_size > 8 * 1024 * 1024:
                    raise ToolError("viewport_capture_failed", "The viewport image exceeded the capture size limit.")
                data = path.read_bytes()
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ToolError("viewport_capture_failed", "Fusion did not return a valid PNG image.")
                return {"ok": True, "document_id": self.document_id, "width": width, "height": height,
                        "view": job["arguments"].get("view", "current"),
                        "framing": "target" if any(key in job["arguments"] for key in ("selection_index", "entity_token")) else "model",
                        "imageUrl": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}
        finally:
            path.unlink(missing_ok=True)

    def inspect_document(self):
        state = self.command_state()
        if not state["readAllowed"]:
            # Metadata only: do not evaluate profiles or traverse a model while
            # the user is editing. An unfamiliar idle command is never trusted.
            return {**self.selection_context(), "commandState": state, "design": None,
                    "inspectionDeferred": True,
                    "guidance": "Only captured context is available while this command is active. "
                    "STEVE has not interrupted it. Generated queries and changes remain queued; "
                    "Stop cancels STEVE's pending request only. If this persists while Fusion is idle, "
                    "report the activeCommand and workspace shown here; do not retry or cancel Fusion commands automatically."}
        context = self.context()
        result = {**self.selection_context(), "products": list(context["products"]),
                  "apiNamespaces": self.namespaces(), "commandState": state, "design": None}
        design = context["design"]
        if design:
            result["design"] = design_summary(design)
        cam = context["products"].get("CAMProductType")
        if cam is not None:
            result["cam"] = cam_summary(adsk.cam.CAM.cast(cam) if hasattr(adsk.cam, "CAM") else cam)
        product = context["product"]
        if "adsk.electron" in result["apiNamespaces"]:
            module = importlib.import_module("adsk.electron")
            for kind in ("Schematic", "Board", "Library", "EcadDesign"):
                cls = getattr(module, kind, None)
                electronic = cls.cast(product) if cls and product else None
                if electronic is not None:
                    result["electronics"] = electronics_summary(electronic)
                    break
        bounded = bounded_result(result)
        return {**bounded.pop("result"), **bounded}

    @staticmethod
    def namespaces():
        return sorted("adsk." + module.name for module in pkgutil.iter_modules(adsk.__path__)
                      if not module.name.startswith("_"))

    def api_help(self, path):
        if path == "steve.helpers":
            return helper_help()
        if path == 'steve.dfm' or path.startswith('steve.dfm.'):
            return {'ok': True, **dfm_guide(path[len('steve.dfm.'):] if path != 'steve.dfm' else None)}
        parts = path.split(".")
        if path == "adsk":
            return {"ok": True, "namespaces": self.namespaces()}
        namespace = ".".join(parts[:2])
        if namespace not in self.namespaces():
            raise ToolError("api_namespace_unavailable", "That Autodesk namespace is not installed.")
        value = importlib.import_module(namespace)
        for part in parts[2:]:
            value = getattr(value, part)
        try:
            signature = str(inspect.signature(value))
        except (ValueError, TypeError):
            signature = None
        return {"ok": True, "path": path, "signature": signature,
                "documentation": (inspect.getdoc(value) or "")[:18000],
                **({"guidance": API_GUIDANCE[path]} if path in API_GUIDANCE else {}),
                "members": [name for name in dir(value) if not name.startswith("_")][:250]}

    def search_docs(self, query, offset=0):
        words = query.casefold().split()
        classes = []
        for namespace in self.namespaces():
            module = importlib.import_module(namespace)
            classes.extend((namespace + "." + name, value) for name, value in vars(module).items()
                           if not name.startswith("_") and inspect.isclass(value))
        classes.sort(key=lambda entry: entry[0])
        matches, scanned = [], 0
        for path, value in classes[offset:offset + 200]:
            scanned += 1
            doc = inspect.getdoc(value) or ""
            members = [name for name in dir(value) if not name.startswith("_")]
            if all(word in (path + " " + doc + " " + " ".join(members)).casefold() for word in words):
                matches.append({"path": path, "description": doc[:600],
                                "matchingMembers": [name for name in members if any(word in name.casefold() for word in words)][:12]})
                if len(matches) >= 10:
                    break
        return {"ok": True, "matches": matches, "scannedClasses": scanned, "totalClasses": len(classes),
                "nextOffset": offset + scanned if offset + scanned < len(classes) else None,
                "scope": "Installed class names, docstrings and member names. Use fusion_api_help on a returned path."}

    def check_target(self, job):
        if self.closed or job["cancelled"]():
            raise ToolError("cancelled", "Operation cancelled before execution.")
        if self.task and self.document is not None and optional_property(self.document, "isValid") is False:
            raise ToolError("target_document_closed", "The task's original document was closed.")
        if job["arguments"].get("document_id", self.document_id) != self.document_id or self.app.activeDocument != self.document:
            raise ToolError("document_changed", "The active document changed.")

    def drain(self):
        if self.closed or self.active is not None:
            return
        try:
            job = self.waiting or self.queue.get_nowait()
            self.waiting = None
        except queue.Empty:
            return
        try:
            if job["cancelled"]():
                raise ToolError("cancelled", "Operation cancelled before execution.")
            if self.task and job["tool"] not in ("fusion_api_help", "fusion_search_docs"):
                if self.document is not None and optional_property(self.document, "isValid") is False:
                    raise ToolError("target_document_closed", "The task's original document was closed.")
                if self.document is None and self.app.activeDocument is not None:
                    raise ToolError("document_changed", "This task started without a document. Send a new request for the newly opened document.")
                if job["arguments"].get("document_id", self.document_id) != self.document_id:
                    raise ToolError("document_changed", "The tool request does not match the task's pinned document.")
                if self.app.activeDocument != self.document:
                    self.wait_for(job, "Waiting for " + (self.task["snapshot"]["name"] or "the task document"))
                    return
                if job["tool"] != "fusion_inspect_document" and not self.check_command(job["tool"]):
                    self.wait_for(job, "Waiting for Fusion command " + str(self.app.userInterface.activeCommand)[:160]
                                  + ". STEVE has not started this operation; Stop cancels only this request.")
                    return
                self.on_wait("", self.task_label())
            if job["tool"] == "fusion_inspect_document":
                self.finish(job, {"ok": True, **self.inspect_document()})
            elif job["tool"] == "fusion_api_help":
                self.finish(job, self.api_help(job["arguments"]["path"]))
            elif job["tool"] == "fusion_search_docs":
                self.finish(job, self.search_docs(job["arguments"]["query"], job["arguments"].get("offset", 0)))
            elif job["tool"] == "fusion_capture_viewport":
                self.finish(job, self.capture_viewport(job))
            elif job["tool"] == "fusion_dfm_plan":
                self.check_target(job)
                self.finish(job, self.dfm_plan(job['arguments']))
            elif job['tool'] == 'fusion_rmfg':
                self.check_target(job)
                if not self.check_command('fusion_rmfg'):
                    raise ToolError('active_command', 'Finish the active Fusion command before preparing this check.')
                self.finish(job, self.rmfg_snapshot(job['arguments']))
            else:
                self.check_target(job)
                if not self.check_command(job["tool"]):
                    raise ToolError("active_command", "Finish or cancel the active Fusion command, then retry this operation.")
                querying = job["tool"] in ("fusion_query_python", "fusion_dfm_check")
                if querying or job["arguments"].get("execution_mode", "command") == "application":
                    result = self.run_script(job)
                    result.update(executionMode="query" if querying else "application", undoGrouped=False)
                    try:
                        result["document"] = self.inspect_document()
                    except Exception as exc:
                        result["inspectionError"] = str(exc)
                    self.verify(job, result)
                    self.finish(job, result)
                    return
                self.definition.name = "STEVE: " + job["arguments"]["title"]
                self.active = job
                if not self.definition.execute():
                    raise RuntimeError("Fusion could not start the operation.")
        except Exception as exc:
            if self.active is job:
                self.active = None
            self.finish(job, tool_failure(exc))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.waiting:
            self.finish(self.waiting, tool_failure(ToolError("cancelled", "STEVE is shutting down.")))
            self.waiting = None
        if self.active:
            self.finish(self.active, tool_failure(ToolError("cancelled", "STEVE is shutting down.")))
            self.active = None
        while not self.queue.empty():
            self.finish(self.queue.get_nowait(), tool_failure(ToolError("cancelled", "STEVE is shutting down.")))
        for event, handler in self.handlers + self.command_handlers:
            try:
                event.remove(handler)
            except RuntimeError:
                pass
        self.handlers.clear()
        self.command_handlers.clear()
        if self.definition.isValid:
            self.definition.deleteMe()
        self.app.unregisterCustomEvent(EVENT_ID)
