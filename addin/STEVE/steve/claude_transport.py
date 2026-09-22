"""Claude subscription inference with STEVE's existing Codex conversation engine."""
import copy
from pathlib import Path
from uuid import uuid4

from .claude_responses import ClaudeGateway
from .claude_setup import account_status, cli_version, discover_models
from .transport import Transport, data_home


class ClaudeTransport(Transport):
    def __init__(self, on_event, home=None, command=None):
        root = Path(home or data_home())
        super().__init__(on_event, home=root / "claude-runtime", command=command)
        self.gateway = None
        self.default_model = None

    def start(self):
        self.gateway = ClaudeGateway(self.home / "replay")
        try:
            super().start()
        except Exception:
            self.close()
            raise

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            return {**account_status(), "providerVersion": cli_version()}
        if method in ("account/login/start", "account/logout"):
            raise ValueError("Manage Claude sign-in outside Fusion with `claude auth login` or `claude auth logout`, then check the connection in STEVE.")
        if method == "account/login/cancel":
            return {}
        if method == "model/list":
            result = discover_models()
            self.default_model = result["data"][0]["id"]
            return result
        if method == "thread/list":
            params["modelProviders"] = ["steve_claude"]
        if method in ("thread/start", "thread/resume"):
            scope = uuid4().hex
            if method == "thread/resume":
                self.gateway.bind(scope, params["threadId"])
            params.setdefault("config", {}).update({
                "model_provider": "steve_claude", "model_providers.steve_claude.name": "Claude",
                "model_providers.steve_claude.base_url": self.gateway.base_url + "/" + scope,
                "model_providers.steve_claude.requires_openai_auth": False,
                "model_providers.steve_claude.wire_api": "responses",
                "model_providers.steve_claude.supports_websockets": False,
                "model_providers.steve_claude.request_max_retries": 0,
                "model_providers.steve_claude.stream_max_retries": 0,
                "web_search": "disabled",
                # Use the conservative native gateway window until model metadata is known.
                "model_context_window": 200000, "model_auto_compact_token_limit": 160000,
                "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]},
            })
            if method == "thread/start":
                if not params.get("model"):
                    if not self.default_model:
                        self.request("model/list")
                    params["model"] = self.default_model
            result = super().request(method, params, **kwargs)
            if method == "thread/start":
                self.gateway.bind(scope, result["thread"]["id"])
            return result
        if method == "turn/start":
            status = account_status()
            if not status["account"]:
                raise RuntimeError(status["localStatus"])
        if method == "turn/interrupt" and self.gateway:
            try:
                return super().request(method, params, **kwargs)
            finally:
                self.gateway.cancel()
        return super().request(method, params, **kwargs)

    def close(self):
        if self.gateway:
            self.gateway.close()
            self.gateway = None
        super().close()
