"""Exercise the bundled runtime without logging in or making a model request."""
import argparse
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
from steve.transport import Transport, bundled_runtime, runtime_command
from steve.controller import thread_start_params


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=ROOT / ".cache" / "smoke-home")
    args = parser.parse_args()
    client = Transport(lambda method, params: None, command=runtime_command(bundled_runtime()), home=args.home.resolve())
    try:
        client.start()
        account = client.request("account/read", {"refreshToken": False})
        print("Handshake OK; ChatGPT signed in:", bool(account.get("account")))
        models = client.request("model/list", {"limit": 5})
        print("Model catalog entries:", len(models.get("data", [])))
        model = models["data"][0]
        effort = model["supportedReasoningEfforts"][-1]["reasoningEffort"]
        try:
            client.request("turn/start", {"threadId": str(uuid4()),
                "input": [{"type": "text", "text": "Schema fixture"},
                          {"type": "image", "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII="}],
                "model": model["model"], "effort": effort})
        except RuntimeError as exc:
            assert "thread not found" in str(exc), str(exc)
        else:
            raise AssertionError("An unknown thread unexpectedly started a turn")
        print("Catalog effort and native image accepted by turn/start schema; unknown thread rejected before inference")
        result = client.request("thread/start", thread_start_params(client.home))
        assert result.get("thread", {}).get("id"), "No thread created"
        print("Thread created with Code Mode enabled")
        try:
            client.request("turn/steer", {"threadId": result["thread"]["id"],
                "expectedTurnId": "no-active-turn", "input": [
                    {"type": "text", "text": "Protocol fixture"},
                    {"type": "image", "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII="}]})
        except RuntimeError as exc:
            assert "no active turn to steer" in str(exc), str(exc)
        else:
            raise AssertionError("Steering an inactive turn unexpectedly succeeded")
        print("Native text/image steering schema accepted; inactive turn correctly rejected")
    finally:
        client.close()
    assert not client.alive, "Runtime did not stop"
    print("Runtime stopped")


if __name__ == "__main__":
    main()
