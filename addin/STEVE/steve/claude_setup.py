"""Ask the official Claude client about its account; never read its credentials."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

INSTALL_HINT = "Install Claude Code, then run `claude auth login` in a terminal outside Fusion. Return here and check the connection."
LOGIN_HINT = "Run `claude auth login` in a terminal outside Fusion, then check the connection here."
INSTALL_URL = "https://code.claude.com/docs/en/setup"


def resolve_claude(command=None, env=None):
    env = os.environ if env is None else env
    configured = env.get("STEVE_CLAUDE_COMMAND")
    command = list(command) if command else [configured or "claude"]
    head = command[0]
    found = shutil.which(head, path=env.get("PATH") or os.defpath)
    if not found and os.path.isabs(head) and Path(head).is_file():
        found = head
    if not found and head == "claude" and not configured:
        # GUI applications often inherit a PATH without the native installer directory.
        candidate = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
        if candidate.is_file():
            found = str(candidate)
    return [found, *command[1:]] if found else None


def checked_environment():
    env = dict(os.environ)
    conflicts = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_FOUNDRY_API_KEY") if env.get(k)]
    conflicts += [k for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
                  if env.get(k, "").lower() not in ("", "0", "false", "no", "off")]
    if conflicts:
        raise ValueError("Claude subscription mode cannot use these environment overrides: " + ", ".join(conflicts) + ". Remove them from Fusion's launch environment and restart Fusion.")
    config = env.pop("STEVE_CLAUDE_CONFIG_DIR", None)
    if config:
        env["CLAUDE_CONFIG_DIR"] = config
    env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DISABLE_AUTOUPDATER="1")
    return env


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def cli_version(command=None):
    """Probe on each connection check so an updated executable is reflected immediately."""
    try:
        env = checked_environment()
        resolved = resolve_claude(command, env)
        if not resolved:
            return ""
        result = subprocess.run([*resolved, "--version"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=10, env=env, **process_options())
        match = re.match(r"^(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)(?:\s|$)", result.stdout.strip())
        return match[1] if result.returncode == 0 and match else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def model_label(model, row):
    """Use the resolved route's version, not an unversioned picker alias."""
    native = row.get("displayName") or row.get("description") or model
    match = re.fullmatch(r"claude-([a-z][a-z-]*?)-(\d+(?:-\d{1,2})*)(?:-\d{8})?(\[[^\]]+\])?", model)
    if not match:
        return native if not model.startswith("claude-") or model in native else f"{native} ({model})"
    name = match[1].replace("-", " ").title() + " " + match[2].replace("-", ".")
    if match[3]:
        name += " (" + match[3][1:-1].upper() + " context)"
    if native.lower().startswith("default"):
        name += " (recommended)"
    return name


def account_status(command=None):
    try:
        env = checked_environment()
    except ValueError as exc:
        return {"account": None, "localStatus": str(exc)}
    resolved = resolve_claude(command, env)
    if not resolved:
        return {"account": None, "localStatus": INSTALL_HINT}
    try:
        result = subprocess.run([*resolved, "auth", "status"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=20, env=env, **process_options())
        auth = json.loads(result.stdout)
        if not isinstance(auth, dict):
            raise ValueError("Expected account metadata")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"account": None, "localStatus": "Claude Code's account check failed. Run `claude auth status` in a terminal, resolve its error, then check again."}
    if result.returncode != 0 or auth.get("loggedIn") is not True:
        return {"account": None, "localStatus": LOGIN_HINT}
    if auth.get("authMethod") != "claude.ai" or auth.get("apiProvider") != "firstParty" or not auth.get("subscriptionType"):
        return {"account": None, "localStatus": "Claude Code must use a Claude subscription, not API billing. Run `claude auth login` outside Fusion and choose your Claude account, then check again."}
    return {"account": {"type": "claude", "email": auth.get("email") or "Claude Code account",
                        "id": auth.get("email") or auth.get("orgId") or "claude-cli",
                        "planType": "Claude " + str(auth["subscriptionType"]).replace("_", " ").title()},
            "localStatus": "Connected through Claude Code. Manage sign-in with `claude auth login` or `claude auth logout` outside Fusion."}


def discover_models(command=None):
    """Native initialize only: no prompt, no paid model request, no pinned fallback."""
    from .claude_native.admission import Admission
    env = checked_environment()
    resolved = resolve_claude(command, env)
    if not resolved:
        raise RuntimeError(INSTALL_HINT)
    gate = Admission("https://api.anthropic.com", 20)
    # Setup is never permitted to generate, even if a future CLI changes its handshake.
    gate.used = True
    try:
        env["ANTHROPIC_BASE_URL"] = gate.url
        args = [*resolved, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--disable-slash-commands", "--no-session-persistence"]
        handshake = json.dumps({"type": "control_request", "request_id": "steve-models", "request": {"subtype": "initialize"}}) + "\n"
        with tempfile.TemporaryDirectory(prefix="steve-claude-models-", ignore_cleanup_errors=True) as cwd:
            result = subprocess.run(args, input=handshake, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30, env=env, cwd=cwd, **process_options())
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        reply = next(row["response"]["response"] for row in rows if row.get("type") == "control_response")
        plan = str((reply.get("account") or {}).get("subscriptionType") or "").lower()
        models = []
        for row in reply.get("models", []):
            model = row.get("resolvedModel") or row.get("value")
            if not model or model in {item["id"] for item in models}:
                continue
            # Use the CLI's exact route and descriptions, including usage-credit notices.
            name = model_label(model, row)
            note = row.get("description") or ""
            credits = "usage credit" in (note + " " + str(row.get("displayName", ""))).lower() or ("fable" in model and plan in ("pro", "claude pro"))
            if credits and "usage credit" not in name.lower():
                name += " · usage credits"
            efforts = row.get("supportedEffortLevels") or []
            efforts = [e for e in efforts if e in ("low", "medium", "high", "xhigh", "max")]
            models.append({"id": model, "model": model, "displayName": name, "isDefault": not models,
                           "supportsImages": True, "defaultReasoningEffort": "high" if "high" in efforts else "",
                           "supportedReasoningEfforts": [{"reasoningEffort": e, "description": "Claude " + e + " effort"} for e in efforts]})
        if not models or gate.denied:
            raise ValueError("No model picker returned")
        return {"data": models, "nextCursor": None}
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
        raise RuntimeError("Claude Code could not list models. Run `claude update` and `claude auth status` outside Fusion, then check the connection again.") from exc
    finally:
        gate.close()
