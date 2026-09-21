"""A subprocess fixture exercising the real JSONL transport, not a mocked pipe."""
import json
from pathlib import Path
import subprocess
import sys

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def send(message):
    print(json.dumps(message), flush=True)


pending_tool = None
linger = None
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"id": request_id, "result": {"userAgent": "steve-test"}})
    elif method == "echo":
        send({"method": "test/event", "params": {"text": "hello"}})
        send({"id": request_id, "result": message["params"]})
    elif method == "fail":
        send({"id": request_id, "error": {"code": 1, "message": "fixture error"}})
    elif method == "exit":
        sys.exit(0)
    elif method == "invalid":
        print("not JSON", flush=True)
    elif method == "tool":
        send({"id": "server-call", "method": "item/tool/call", "params": {}})
        response = json.loads(next(sys.stdin))
        send({"id": request_id, "result": {"declined": response.get("error", {}).get("code") == -32601}})
    elif method == "ignore":
        pass
    elif method == "stderr":
        print("fixture diagnostic", file=sys.stderr, flush=True)
        send({"id": request_id, "result": {}})
    elif method == "deferred-tool":
        pending_tool = request_id
        send({"id": "deferred", "method": "item/tool/call", "params": {"tool": "fusion_inspect_document", "arguments": {}}})
        send({"method": "test/while-tool-pending", "params": {}})
    elif method is None and request_id == "deferred":
        send({"id": pending_tool, "result": message["result"]})
    elif method == "linger":
        linger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        send({"id": request_id, "result": {"pid": linger.pid}})

if linger is not None:
    # Ignore the shutdown request so the client must stop the whole process tree.
    linger.wait()
Path("closed-cleanly.txt").write_text("stdin EOF", encoding="utf-8")
