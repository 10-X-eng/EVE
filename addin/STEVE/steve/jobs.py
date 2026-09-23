"""User job commands; Codex owns persistence, accounting, and continuation."""
import re


def job_command(text):
    match = re.fullmatch(r"/jobs(?:\s+([\s\S]*))?", text.strip())
    if not match:
        return None
    value = (match[1] or "").strip()
    if not value or value in ("status", "pause", "resume", "clear", "edit", "help"):
        return {"command": value or "status"}
    word, _, rest = value.partition(" ")
    if word in ("pause", "resume", "clear", "status", "help"):
        raise ValueError(f"Use /jobs {word} without extra text.")
    return {"command": "set", "objective": rest.strip() if word == "edit" else value}


def validate_job(payload):
    command = payload.get("command", "status")
    if command not in ("status", "set", "pause", "resume", "clear", "edit", "help"):
        raise ValueError("Use /jobs, /jobs <objective>, /jobs edit, /jobs pause, /jobs resume, or /jobs clear.")
    result = {"command": command}
    if command == "set":
        objective = payload.get("objective")
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
            raise ValueError("A job needs an objective of 1–4,000 characters.")
        result["objective"] = objective.strip()
    if "tokenBudget" in payload:
        budget = payload["tokenBudget"]
        if budget is not None and (type(budget) is not int or not 1 <= budget <= 2**53 - 1):
            raise ValueError("Use a positive whole number for the token budget, or leave it blank.")
        result["tokenBudget"] = budget
    return result
