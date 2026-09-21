"""Run one generated operation. This is in-process execution, not a sandbox."""
import ast
import builtins
import json
import sys
import time
import traceback

from .tool_protocol import ToolError, tool_failure

FILENAME = "<STEVE script>"
RESULT_LIMIT = 24000


def bounded_result(value):
    # Stop counting once the response is too large; don't serialize an entire
    # tool library just to determine its exact size.
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(value):
        size += len(chunk)
        if size > RESULT_LIMIT:
            break
    else:
        return {"result": value}

    remaining = 16000
    omissions = []

    def omitted(path, **details):
        if len(omissions) < 20:
            omissions.append({"path": path[:200], **details})

    def preview(item, path="$", depth=0):
        nonlocal remaining
        if isinstance(item, (dict, list, tuple)):
            remaining -= 2
            mapping = isinstance(item, dict)
            result = {} if mapping else []
            entries = item.items() if mapping else enumerate(item)
            if depth < 5:
                for key, child in entries:
                    if len(result) >= 20 or remaining < 128:
                        break
                    key_cost = len(json.dumps(str(key), ensure_ascii=False)) + 2 if mapping else 1
                    if key_cost > min(256, remaining - 64):
                        break
                    remaining -= key_cost
                    part = preview(child, f"{path}.{key}" if mapping else f"{path}[{key}]", depth + 1)
                    if mapping:
                        result[key] = part
                    else:
                        result.append(part)
            if len(result) < len(item):
                omitted(path, returned=len(result), total=len(item))
            return result
        if isinstance(item, str):
            # Worst-case JSON escaping takes six characters per input character.
            shown = item[:min(1000, max(0, (remaining - 2) // 6))]
            if len(shown) < len(item):
                omitted(path, returnedCharacters=len(shown), totalCharacters=len(item))
            item = shown
        encoded = json.dumps(item, ensure_ascii=False)
        if len(encoded) > remaining:
            omitted(path, valueOmitted=True)
            item, encoded = None, "null"
        remaining -= len(encoded)
        return item

    result = preview(value)
    return {"result": result, "resultTruncated": True,
            "resultLimit": RESULT_LIMIT, "omitted": omissions,
            "guidance": "The script ran successfully; this is only a partial preview, not the complete result. "
                        "Do not repeat a modifying operation to recover output. Use fusion_query_python to read "
                        "only the needed fields from a smaller filtered page (start with 20 items), returning "
                        "total, offset, returned, and nextOffset. Do not treat missing data as absent."}


class ScriptStopped(BaseException):
    def __init__(self, message, code="cancelled"):
        super().__init__(message)
        self.code = code


def run_python(source, context, cancelled=lambda: False, budget_seconds=15, diagnostic=None):
    output = []
    remaining = 12000
    output_truncated = False
    started = time.monotonic()
    execution_started = False
    formatting_result = False
    traced_lines = set()

    def capture(*values, sep=" ", end="\n", **kwargs):
        nonlocal remaining, output_truncated
        text = sep.join(str(value) for value in values) + end
        output_truncated = output_truncated or len(text) > remaining
        if remaining:
            output.append(text[:remaining])
        remaining = max(0, remaining - len(text))

    def trace(frame, event, arg):
        if frame.f_code.co_filename == FILENAME:
            if cancelled():
                raise ScriptStopped("Operation cancelled.")
            if time.monotonic() - started > budget_seconds:
                raise ScriptStopped("Python execution exceeded its time budget. Use a smaller operation.", "python_time_budget")
            if diagnostic and event == "line" and frame.f_lineno not in traced_lines:
                traced_lines.add(frame.f_lineno)
                diagnostic("python.line_entered", line=frame.f_lineno, function=frame.f_code.co_name)
        return trace

    previous_trace = sys.gettrace()
    try:
        tree = ast.parse(source, filename=FILENAME)
        for node in ast.walk(tree):
            if (context.get("targetPinned") and isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Load) and node.attr in
                    {"activeDocument", "activeProduct", "activeSelections", "activeWorkspace", "activeProject", "activeFolder", "activeHub"}):
                raise ToolError("live_context_access", f"Line {node.lineno}: {node.attr} follows the user's current UI and can retarget the task. Use STEVE's pinned context instead.")
            if (isinstance(node, ast.Attribute) and node.attr == "objectType"
                    and isinstance(node.value, ast.Attribute) and node.value.attr == "value"):
                raise ToolError("unsafe_value_introspection", f"Line {node.lineno}: do not discover parameter types by evaluating .value.objectType; this pattern triggered a native Fusion probing crash. Read names/expressions and the documented value class instead.")
        if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
            raise ValueError("Define def run(context) with the operation inside it. STEVE calls run once.")
        if cancelled():
            raise ScriptStopped("Operation cancelled before execution.")
        namespace = {"__name__": "__steve_script__", "__builtins__": {**vars(builtins), "print": capture}}
        sys.settrace(trace)
        execution_started = True
        exec(compile(tree, FILENAME, "exec"), namespace)
        value = namespace["run"](context)
        formatting_result = True
        result = {"ok": True, "output": "".join(output), "outputTruncated": output_truncated,
                  **bounded_result(value)}
        if output_truncated:
            result["outputGuidance"] = "Printed output is incomplete. Do not repeat changes for missing output; query selected fields or smaller pages and return structured JSON instead of printing a dump."
        return result
    except BaseException as exc:
        frames = [f"line {frame.lineno} in {frame.name}" for frame in traceback.extract_tb(exc.__traceback__)
                  if frame.filename == FILENAME]
        return {**tool_failure(exc, code="invalid_result" if formatting_result else None,
                               execution_started=execution_started),
                "output": "".join(output), "outputTruncated": output_truncated, "trace": frames}
    finally:
        sys.settrace(previous_trace)
