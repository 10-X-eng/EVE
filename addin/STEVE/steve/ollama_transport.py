"""Local Ollama discovery and the bundled conversation runtime's Responses provider."""
import copy
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .transport import Transport, data_home

BASE_URL = "http://127.0.0.1:11434"
MAX_METADATA = 4 * 1024 * 1024
MIN_CONTEXT = 8192


class OllamaError(RuntimeError):
    pass


class UnsupportedModel(OllamaError):
    pass


def cloud_name(model):
    return ":cloud" in model.lower() or model.lower().endswith("-cloud")


class OllamaAPI:
    def __init__(self):
        # Never route local model metadata through a system HTTP proxy.
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, body=None, timeout=5):
        request = Request(BASE_URL + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise OllamaError("Ollama returned too much model metadata. Update Ollama, then refresh models.")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError("Invalid model metadata")
            return result
        except HTTPError as exc:
            exc.close()
            raise OllamaError("Ollama could not load the requested model. Check that it is downloaded and fits in memory, then refresh models.") from exc
        except TimeoutError as exc:
            raise OllamaError("Ollama took too long to respond. Check available memory or choose a smaller model, then retry.") from exc
        except (URLError, OSError) as exc:
            raise OllamaError("Cannot reach Ollama at localhost:11434. Start the Ollama app, then choose Refresh models.") from exc
        except (ValueError, TypeError) as exc:
            raise OllamaError("Ollama returned invalid model information. Update Ollama, then refresh models.") from exc

    def inspect(self, model):
        info = self.request("/api/show", {"model": model})
        if info.get("remote_model") or info.get("remote_host") or cloud_name(model):
            raise UnsupportedModel("Choose a downloaded local model. STEVE's Ollama provider does not use cloud models.")
        capabilities = info.get("capabilities") or []
        if "tools" not in capabilities or "completion" not in capabilities:
            raise UnsupportedModel("This model does not support tool calling. Download a model with tools support, then refresh models.")
        return info

    def models(self):
        models = []
        for entry in self.request("/api/tags").get("models", []):
            name = entry.get("name", "")
            if not isinstance(name, str) or not name or cloud_name(name):
                continue
            try:
                info = self.inspect(name)
            except UnsupportedModel:
                continue
            configured = re.search(r"(?m)^num_ctx\s+(\d+)", info.get("parameters", ""))
            models.append({"id": name, "model": name, "displayName": name,
                           "defaultReasoningEffort": "", "supportedReasoningEfforts": [],
                           "supportsImages": "vision" in info["capabilities"],
                           "configuredContext": int(configured[1]) if configured else 0,
                           "size": entry.get("size", 0)})
        models.sort(key=lambda m: (m["configuredContext"] < MIN_CONTEXT, m["size"], m["id"]))
        for index, model in enumerate(models):
            model["isDefault"] = index == 0
        return {"data": models}

    def prepare(self, model):
        info = self.inspect(model)
        # Use the model's saved settings. A temporary num_ctx override is lost on /v1/responses.
        self.request("/api/generate", {"model": model, "stream": False, "keep_alive": "5m"}, timeout=180)
        running_models = self.request("/api/ps").get("models", [])
        running = next((m for m in running_models if model in (m.get("name"), m.get("model"))), None)
        if running is None:
            # Ollama reuses a loaded parent's runner for aliases with the same weights/settings.
            parent = (info.get("details") or {}).get("parent_model")
            running = next((m for m in running_models if parent and parent in (m.get("name"), m.get("model"))), {})
        allocated = running.get("context_length", 0)
        metadata = info.get("model_info") or {}
        supported = metadata.get(str(metadata.get("general.architecture", "")) + ".context_length")
        if isinstance(supported, int) and supported > 0 and isinstance(allocated, int):
            allocated = min(allocated, supported)
        if not isinstance(allocated, int) or allocated < MIN_CONTEXT:
            raise OllamaError("This model has less than 8K context allocated. Set num_ctx to at least 8192 in an Ollama Modelfile, create that model, then select it in STEVE. See Local setup.")
        return {"model": model, "context": allocated, "vision": "vision" in info["capabilities"]}


class OllamaTransport(Transport):
    def __init__(self, on_event, home=None, command=None, api=None):
        super().__init__(on_event, home=(home or data_home()) / "ollama-runtime", command=command)
        self.api = api or OllamaAPI()
        self.default_model = None
        self.threads = {}

    @staticmethod
    def config(prepared):
        context = prepared["context"]
        return {"model_provider": "steve_ollama", "model_providers.steve_ollama.name": "Ollama (local)",
                "model_providers.steve_ollama.base_url": BASE_URL + "/v1",
                "model_providers.steve_ollama.requires_openai_auth": False,
                "model_providers.steve_ollama.wire_api": "responses",
                "model_providers.steve_ollama.supports_websockets": False,
                "model_context_window": context, "model_auto_compact_token_limit": context - max(2048, context // 4),
                "model_supports_reasoning_summaries": False, "web_search": "disabled",
                "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]}}

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            try:
                info = self.api.request("/api/version")
                version = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(info.get("version", "")))
                if not version or tuple(map(int, version.groups())) < (0, 13, 3):
                    raise OllamaError("Update Ollama to 0.13.3 or newer for Responses API support, then refresh models.")
            except OllamaError as exc:
                return {"account": None, "localStatus": str(exc)}
            return {"account": {"type": "ollama", "id": "local-ollama", "email": "Local Ollama", "planType": "On this computer"},
                    "localStatus": "Connected to localhost:11434. No sign-in needed."}
        if method.startswith("account/"):
            raise OllamaError("Ollama runs locally and needs no sign-in. Start Ollama and refresh models.")
        if method == "model/list":
            result = self.api.models()
            self.default_model = next((m["id"] for m in result["data"] if m["isDefault"]), None)
            return result
        if method == "thread/list":
            params["modelProviders"] = ["steve_ollama"]
        if method in ("thread/start", "thread/resume"):
            model = params.get("model")
            if not model and method == "thread/resume":
                saved = super().request("thread/read", {"threadId": params["threadId"], "includeTurns": False})
                model = saved.get("thread", {}).get("model")
            model = model or self.default_model
            if not model:
                raise OllamaError("Download a local model with tools support, then choose Refresh models.")
            prepared = self.api.prepare(model)
            params["model"] = model
            params.setdefault("config", {}).update(self.config(prepared))
            params["baseInstructions"] = params.get("baseInstructions", "") + "\nThis is a local Ollama session. Web search is unavailable. Use fusion_api_help for installed Fusion API documentation. Keep tool results small."
            result = super().request(method, params, **kwargs)
            self.threads[result["thread"]["id"]] = prepared
            return result
        if method == "turn/start":
            previous = self.threads.get(params["threadId"], {})
            model = params.get("model") or previous.get("model") or self.default_model
            prepared = self.api.prepare(model)
            if previous != prepared:
                super().request("thread/resume", {"threadId": params["threadId"], "model": model,
                                                "config": self.config(prepared)})
                self.threads[params["threadId"]] = prepared
            params["model"] = model
        if method in ("turn/start", "turn/steer"):
            prepared = self.threads.get(params["threadId"], {})
            if not prepared.get("vision") and any(item.get("type") in ("image", "localImage") for item in params.get("input", [])):
                raise OllamaError("This model cannot read images. Select a local model with vision support, then resend the image.")
        return super().request(method, params, **kwargs)
