"""Bounded evidence, not a general proof of design intent or machining safety."""
import math
from .document_summary import field


class Checks:
    def __init__(self):
        self.results = []

    def check(self, label, actual, expected, tolerance=0.0, units=""):
        """Record a measured scalar comparison; never change geometry or abort a command."""
        if len(self.results) >= 20:
            raise ValueError("At most 20 verification checks per operation.")
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("Use a short verification label.")
        if not isinstance(units, str) or len(units) > 40:
            raise ValueError("Use a short units label.")
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("Tolerance must be finite and nonnegative.")
        for value in (actual, expected):
            if type(value) not in (str, bool, int, float) or (isinstance(value, str) and len(value) > 200):
                raise ValueError("Checks require bounded scalar measurements, not API objects.")
            if type(value) in (int, float) and not math.isfinite(value):
                raise ValueError("Measurements must be finite.")
        numeric = type(actual) in (int, float) and type(expected) in (int, float)
        passed = abs(actual - expected) <= tolerance if numeric else type(actual) is type(expected) and actual == expected
        self.results.append(dict(label=label, actual=actual, expected=expected, tolerance=tolerance,
                                 units=units, passed=passed))
        return passed


def snapshot(design, limit=80):
    result = {"design": design, "entries": [], "complete": False}
    if design is None:
        result["unavailable"] = "Automatic feature checks apply to Design only. Query this product explicitly."
        return result
    try:
        components = design.allComponents
        for ci in range(min(components.count, 40)):
            features = components.item(ci).features
            for fi in range(features.count):
                if len(result["entries"]) >= limit:
                    return result
                feature = features.item(fi)
                result["entries"].append({"ref": feature, "token": field(feature, "entityToken"),
                                          "name": field(feature, "name"), "health": field(feature, "healthState"),
                                          "message": field(feature, "errorOrWarningMessage")})
        result["complete"] = components.count <= 40
    except (AttributeError, RuntimeError) as exc:
        result["unavailable"] = str(exc)[:160]
    return result


def report(before, after, checks, execution_ok, healthy_state):
    created, changed, deleted, new_problems, existing_problems, unclassified = [], [], [], [], [], []
    comparable = before["design"] is not None and before["design"] == after["design"]
    resolved = []
    complete = comparable and before["complete"] and after["complete"]
    if comparable:
        for old in before["entries"]:
            try:
                matches = before["design"].findEntityByToken(old["token"]) if isinstance(old["token"], str) else [old["ref"]]
                if not matches:
                    deleted.append(old["name"])
                resolved.append((old, matches))
            except (AttributeError, RuntimeError):
                complete = False
                resolved.append((old, [old["ref"]]))
    for current in after["entries"]:
        old = next((entry for entry, matches in resolved if any(current["ref"] == entity for entity in matches)), None)
        details = {key: current[key] for key in ("name", "health", "message")}
        if old is None and comparable and before["complete"]:
            created.append(current["name"])
        elif old and any(current[key] != old[key] for key in ("name", "health", "message")):
            changed.append(details)
        if isinstance(current["health"], dict):
            complete = False
        elif current["health"] != healthy_state:
            (unclassified if old is None and (not comparable or not before["complete"]) else
             existing_problems if old and current["health"] == old["health"] and current["message"] == old["message"]
             else new_problems).append(details)
    failed = not execution_ok or new_problems or unclassified or any(not check["passed"] for check in checks)
    return {"status": "failed" if failed else "passed_checks" if complete and checks else "incomplete",
            "scope": "First 80 Design features across at most 40 components; not a geometry diff.",
            "complete": bool(complete), "createdFeatures": created[:20], "changedFeatures": changed[:20],
            "deletedFeatures": deleted[:20], "newProblems": new_problems[:20], "existingProblems": existing_problems[:20],
            "unclassifiedProblems": unclassified[:20],
            "detailsTruncated": any(len(items) > 20 for items in (created, changed, deleted, new_problems, existing_problems)),
            "checks": checks, "unavailable": after.get("unavailable"),
            "guidance": "Execution success is not design verification. Report failed or missing checks; query current state "
                        "before correcting partial work. No automatic replay or rollback. Only listed checks were evaluated."}
