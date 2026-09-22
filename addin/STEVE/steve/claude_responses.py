"""Translate Codex Responses turns into the official Claude client's model requests."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import queue
import secrets
import threading
from uuid import uuid4

from .claude_native.directsdk import Client, projection
from .loopback_http import ThreadingLoopbackHTTPServer
from .claude_setup import account_status


class ReplayStore:
    """Retain native signed blocks only for an identical model and visible message."""
    def __init__(self, folder):
        self.folder = Path(folder)

    def path(self, model, message):
        key = json.dumps([model, projection(message)], sort_keys=True, ensure_ascii=False)
        return self.folder / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def save(self, model, message):
        details = message.get("reasoning_details")
        if not details:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.path(model, message)
        temporary = path.with_suffix("." + uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def restore(self, model, message):
        path = self.path(model, message)
        try:
            if path.stat().st_size <= 16 * 1024 * 1024:
                message["reasoning_details"] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass


def content(parts):
    if isinstance(parts, str):
        return parts
    result = []
    for part in parts or []:
        kind = part.get("type")
        if kind in ("input_text", "output_text", "text"):
            result.append({"type": "text", "text": part.get("text", "")})
        elif kind == "input_image":
            url = part.get("image_url", "")
            if not isinstance(url, str) or not url.startswith("data:image/") or ";base64," not in url:
                raise ValueError("Claude images must be attached as image data. Attach the image again and retry.")
            result.append({"type": "image_url", "image_url": {"url": url}})
        else:
            raise ValueError("Claude cannot replay this content type: " + str(kind))
    return result


def translate(body, replay):
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("Choose a Claude model and retry.")
    messages, systems = [], []
    if body.get("instructions"):
        systems.append(body["instructions"])
    inputs = body.get("input", [])
    if isinstance(inputs, str):
        inputs = [{"role": "user", "content": inputs}]
    for item in inputs:
        kind = item.get("type", "message")
        if kind == "reasoning":
            continue  # Provider-native signatures live in the projection-checked replay store.
        if kind == "message":
            role = item["role"]
            parts = content(item.get("content"))
            if role in ("system", "developer"):
                if not isinstance(parts, str):
                    parts = "\n".join(part["text"] for part in parts if part["type"] == "text")
                # Codex includes current environment/developer context amongst history.
                # Keep it in chronological order when it isn't an initial instruction.
                if messages:
                    messages.append({"role": "user", "content": parts})
                else:
                    systems.append(parts)
            elif role == "assistant":
                text = parts if isinstance(parts, str) else "".join(p["text"] for p in parts)
                if messages and messages[-1]["role"] == "assistant":
                    messages[-1]["content"] = (messages[-1].get("content") or "") + text
                else:
                    messages.append({"role": "assistant", "content": text})
            else:
                messages.append({"role": role, "content": parts})
        elif kind == "function_call":
            if not messages or messages[-1]["role"] != "assistant":
                messages.append({"role": "assistant", "content": ""})
            messages[-1].setdefault("tool_calls", []).append({"id": item["call_id"], "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]}})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": content(item.get("output", ""))})
        else:
            raise ValueError("Claude cannot replay this conversation item: " + str(kind) + ". Start a new Claude chat.")
    for message in messages:
        if message["role"] == "assistant":
            replay.restore(model, message)
    if systems:
        messages.insert(0, {"role": "system", "content": "\n\n".join(systems)})
    tools = []
    for tool in body.get("tools", []):
        if tool.get("type") != "function":
            raise ValueError("Claude currently supports STEVE function tools only; web search must be disabled.")
        tools.append({"type": "function", "function": {key: copy.deepcopy(tool[key]) for key in
                      ("name", "description", "parameters") if key in tool}})
    params = {"model": model, "messages": messages, "tools": tools, "stream": True}
    if body.get("max_output_tokens"):
        params["max_tokens"] = body["max_output_tokens"]
    effort = (body.get("reasoning") or {}).get("effort")
    if effort:
        params["extra_body"] = {"reasoning": {"enabled": effort != "none", "effort": effort}}
    if body.get("tool_choice") not in (None, "auto"):
        raise ValueError("Claude subscription mode requires automatic tool selection.")
    return params


def response_events(params, client, replay):
    rid, mid = "resp_" + uuid4().hex, "msg_" + uuid4().hex
    base = {"id": rid, "object": "response", "model": params["model"], "output": [], "status": "in_progress"}
    yield {"type": "response.created", "response": base}
    message = {"id": mid, "type": "message", "role": "assistant", "status": "in_progress", "content": []}
    text, started, final = "", False, None
    stream = client.create(**params)
    try:
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                if not started:
                    started = True
                    yield {"type": "response.output_item.added", "output_index": 0, "item": copy.deepcopy(message)}
                    yield {"type": "response.content_part.added", "item_id": mid, "output_index": 0,
                           "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}}
                text += delta
                yield {"type": "response.output_text.delta", "item_id": mid, "output_index": 0, "content_index": 0, "delta": delta}
            if hasattr(chunk, "_response"):
                final = chunk._response.model_dump()
    finally:
        stream.close()
    if final is None:
        raise RuntimeError("Claude ended without a complete response. Retry the message.")
    choice = final["choices"][0]
    native_messages = [m for carrier in choice["message"].get("reasoning_details", []) for m in carrier.get("messages", [])]
    if choice["finish_reason"] == "length" or any(m.get("stop_reason") in ("max_tokens", "model_context_window_exceeded") for m in native_messages):
        raise RuntimeError("Claude reached its output or context limit. Ask for a smaller operation or start a new chat; incomplete tools were not executed.")
    assistant = final["choices"][0]["message"]
    replay.save(params["model"], assistant)
    output = []
    if started:
        message.update(status="completed", content=[{"type": "output_text", "text": text, "annotations": []}])
        yield {"type": "response.output_text.done", "item_id": mid, "output_index": 0, "content_index": 0, "text": text}
        yield {"type": "response.output_item.done", "output_index": 0, "item": message}
        output.append(message)
    for call in assistant.get("tool_calls") or []:
        item = {"id": "fc_" + uuid4().hex, "type": "function_call", "status": "completed",
                "call_id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]}
        yield {"type": "response.output_item.added", "output_index": len(output), "item": item}
        yield {"type": "response.output_item.done", "output_index": len(output), "item": item}
        output.append(item)
    u = final["usage"]
    usage = {"input_tokens": u["prompt_tokens"], "output_tokens": u["completion_tokens"], "total_tokens": u["total_tokens"]}
    if u.get("prompt_tokens_details"):
        usage["input_tokens_details"] = u["prompt_tokens_details"]
    if u.get("completion_tokens_details"):
        usage["output_tokens_details"] = u["completion_tokens_details"]
    yield {"type": "response.completed", "response": {**base, "status": "completed", "output": output, "usage": usage}}


def subscription_client():
    status = account_status()
    if not status['account']:
        raise RuntimeError(status['localStatus'])
    return Client()


class ClaudeGateway:
    def __init__(self, folder, client_factory=subscription_client):
        self.folder = Path(folder)
        self.scopes = {}
        self.client_factory = client_factory
        self.lock = threading.Lock()
        self.active = set()
        self.closed = False
        route = "/" + secrets.token_urlsafe(32)
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                parts = self.path.split("/")
                with gateway.lock:
                    replay = gateway.scopes.get(parts[-2]) if len(parts) == 4 else None
                if not self.path.startswith(route + "/") or parts[-1] != "responses" or not replay or self.headers.get("Origin"):
                    self.send_error(404)
                    return
                client, worker = None, None
                try:
                    self.connection.settimeout(30)
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 64 * 1024 * 1024:
                        self.send_error(413)
                        return
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("Incomplete Claude request")
                    params = translate(json.loads(raw), replay)
                    with gateway.lock:
                        if gateway.closed:
                            raise RuntimeError("Claude connection closed")
                        client = gateway.client_factory()
                        gateway.active.add(client)
                except Exception as exc:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": {"message": str(exc)}}).encode())
                    return
                events = queue.Queue()
                def generate():
                    try:
                        for event in response_events(params, client, replay):
                            events.put(event)
                    except Exception as exc:
                        events.put({"type": "response.failed", "response": {"status": "failed", "output": [],
                                    "error": {"message": str(exc), "code": "claude_request_failed"}}})
                    finally:
                        events.put(None)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    worker = threading.Thread(target=generate, daemon=True, name="STEVE-Claude-request")
                    worker.start()
                    while True:
                        try:
                            event = events.get(timeout=.5)
                        except queue.Empty:
                            packet = b": keepalive\n\n"
                        else:
                            if event is None:
                                break
                            packet = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                        self.wfile.write(packet)
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    client.cancel()
                    if worker:
                        worker.join(timeout=10)
                    if not worker or not worker.is_alive():
                        client.close()
                    with gateway.lock:
                        gateway.active.discard(client)
                    self.close_connection = True

            def log_message(self, *args):
                pass

        self.server = ThreadingLoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}{route}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()

    def bind(self, scope, thread_id):
        # Identical visible answers from different chats must never share signed reasoning.
        folder = self.folder / hashlib.sha256(thread_id.encode()).hexdigest()
        with self.lock:
            self.scopes[scope] = ReplayStore(folder)

    def cancel(self):
        with self.lock:
            for client in self.active:
                client.cancel()

    def close(self):
        with self.lock:
            self.closed = True
        self.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
