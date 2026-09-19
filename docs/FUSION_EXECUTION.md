# Let Codex write Fusion Python

Status: implemented prototype. Automated bridge tests and real app-server registration pass. Model-driven geometry creation and Undo still need live Fusion verification.

EVE supplies a small in-process bridge. Codex provides Code Mode, tool calling, authentication, persistent conversations, and the loop that uses tool results to decide what to do next. There is no separate planner or catalog of individual modeling commands.

## Five tools

- `fusion_inspect_document`: return an opaque document identity, available products, active workspace, selection, and bounded design summaries when available.
- `fusion_query_python`: the default for questions and data gathering. Read or search model details, CAM setups, assigned machines, document tools, and accessible local/cloud libraries with generated Python. It uses the same runner and context as execution, without starting a Fusion command.
- `fusion_api_help`: discover installed Autodesk namespaces and read public API signatures, documentation, and members without invoking methods.
- `fusion_execute_python`: run an operation through any installed Fusion Python API, including modeling, assemblies, parameters, CAM, and other exposed products.
- `fusion_capture_viewport`: render the current model view to a bounded PNG, preserving the camera, and deliver it through native Codex image input for visual verification.

Tool descriptions and the current instructions direct EVE to query available machines and tools before choosing them for CAM work, and to query real state rather than ask the user to manually supply it. Queries are read-only by contract, not by a separate sandbox: they share the same in-process Python capabilities. Mutation belongs in the execution tool. Both paths retain document targeting, queued cancellation, captured output/errors, and optional debug logging. Live model tool selection still needs verification.

App-server initialization enables `experimentalApi`. New persistent threads register these tools through `thread/start.dynamicTools`; resumed threads retain their original declarations. After updating the chat-only prototype, start a new conversation for the new tools.

## Script contract

Source must define `run(context)`. EVE invokes it once on Fusion's main thread; put the requested work inside that function. An inspection-only example:

```python
def run(context):
    return {"products": list(context["products"])}
```

Context includes `app`, `ui`, `document`, active `product`, `products` keyed by product type, and `design`, `root`, and `units` when a design exists. Import installed `adsk` modules as needed. Each invocation has fresh globals. Return a small JSON-compatible result; printed output and script errors are captured. API help comes from the installed wrappers so EVE can check signatures for the user's Fusion version.

Context also includes `data` (`app.data`) and up to 100 live `selection` entities with the full `selectionCount`. Each message carries a bounded Send-time snapshot of selection names/types/tokens and the Data Panel's hub/project/folder. EVE can resolve original entity tokens if selection subsequently changes; it must not silently retarget the operation.

The task now retains the original entity references and snapshot. `selectionInvalidCount` reports references invalidated by later edits; current UI selections never fill those gaps. The runner rejects direct `activeDocument`, `activeProduct`, `activeSelections`, `activeWorkspace`, and active Data Panel scope getters while pinned, with instructions to use `context` instead. This is an accidental-retargeting guard, not isolation from arbitrary Python.

The bridge holds a pending tool request when another document or a user command is active. Document-activation/closure and command-termination events wake the queue on Fusion's main thread; there is no busy loop, focus stealing, or automatic user-command cancellation. Stop wakes and cancels pending work. The target is checked again at command execution; a tab switch before generated code begins safely defers the operation without replaying executed code. A closed target returns a terminal recovery instruction. An application-mode script that intentionally changes documents transfers the pin to its resulting context.

Data Panel search uses the query runner to traverse requested projects/folders in bounded pages, returning file IDs, names, versions and locations. It uses the existing Autodesk session. Assembly insertion uses `data.findFileById` and `root.occurrences.addByInsert` through the execution runner. Instructions require resolving ambiguous matches and explaining unsupported cross-project links before substituting embedded copies. This is conversational search through generated Python, not a replacement Data Panel UI or a global cloud search index.

`execution_mode` defaults to `command` for modeling. Choose `application` for APIs that Autodesk prohibits within command transactions, such as creating or closing documents. Application mode runs from the main-thread custom event, with the same document and cancellation checks, but without a command transaction, grouped Undo, or automatic rollback. Keep document operations separate from modeling and inspect again before working in the resulting document. The returned state includes its new document identity.

The transport reader queues work and calls `fireCustomEvent`; document access and Python execution occur on Fusion's main thread. The reader remains available for notifications and cancellation while work is pending. Execution requires the identity returned by inspection, rechecked when the command starts. EVE rejects a changed document or an unrelated active Fusion command.

Model edits run inside a command's `execute` handler so Fusion can group them into one Undo operation. Script failure sets `executeFailed`, requesting that Fusion abort the command transaction. After command destruction, the bridge checks Fusion's final termination reason and returns observed document state with the result. Successful Python alone does not count as a completed command. File, document, manufacturing, and external operations may have different Undo semantics; rollback is not guaranteed for all APIs.

## Limits and verification

Generated Python runs with Fusion's process privileges, not inside Codex's subprocess sandbox. Instructions constrain it to user-requested Fusion work and prohibit arbitrary files, credentials, network, and process access; those instructions are not a security boundary.

Queued work can be cancelled. Python tracing checks cancellation and a 15-second budget while generated Python executes, but cannot forcibly interrupt a native geometry calculation. Scripts should remain bounded. Output and result sizes are limited.

Results over 24,000 JSON characters return a successful bounded preview with truncation metadata and recovery guidance, so output size alone does not abort a modeling command. Printed output is capped at 12,000 characters. Instructions direct the model to filter/page queries and never repeat a modifying script merely to recover its output. Errors include `errorCode`, `executionStarted`, and concrete `recovery` instructions for correcting syntax/signatures, stale targets, active commands, cancellation, and other failures.

Mid-loop messages use `turn/steer` with `expectedTurnId`; stale messages never start a new turn silently. The UI retains unconfirmed messages. Viewport capture uses the same native steering route with an image input, avoiding nested dynamic-tool image replay problems. Capture is limited to 1280 pixels on the longest edge and 8 MiB; temporary files are removed, and image data is excluded from debug logs. Image delivery is verified at the protocol level, not proof that a model interpreted it correctly.

Live web search is enabled for public Autodesk documentation. Shell, browser automation, apps and other unrelated runtime features remain disabled. Installed API help remains the source for the exact locally available signatures.

The model catalog supplies `supportedReasoningEfforts` and `defaultReasoningEffort`. `turn/start` receives the selected model and effective `effort`; model defaults are sent explicitly to clear previous turn overrides. Local preferences retain the model and a separate effort choice per model, including the account-default option. Model/effort controls are disabled during a running turn; steering does not change them.

Automated tests cover deferred execution, general product access, document switching, cancellation, failure reporting, command transaction flags, API help, output bounds, and keeping the transport responsive during pending work. The actual pinned Codex runtime accepts the controller's tool declarations. These checks do not prove live model creation or broad Autodesk API coverage.

The first live checks should create a parametric component, verify dimensions and bodies through the API, undo it once, and exercise a deliberate error followed by a correction. Also inspect an assembly and a manufacturing workspace. Report specific API gaps rather than claiming every Fusion UI feature is supported.

## Official references

- [Fusion Python API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
- [Fusion threading and custom events](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm)
- [Fusion commands and Undo transactions](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Commands_UM.htm)
- [Command execution failure](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_CommandEventArgs_executeFailed.htm)
- [Command termination reasons](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_CommandTerminationReason.htm)
- [Document creation and command transaction restrictions](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Documents_add.htm)
- [Fusion API units](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Units_UM.htm)
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)
- [Data Panel data access](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Data.htm)
- [Inserting existing designs](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_Occurrences_addByInsert.htm)
- [Viewport capture](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Viewport_saveAsImageFile.htm)
- [Fusion toolbar and QAT](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/UserInterface_UM.htm)
- [Codex web search](https://learn.chatgpt.com/docs/web-search)

Documentation checked September 19, 2026.
