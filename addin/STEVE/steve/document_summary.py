"""Small, read-only product summaries. No profile computation or library scans."""


def field(obj, name):
    try:
        value = getattr(obj, name)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:200]
        return {"unavailable": "Not a scalar property"}
    except (AttributeError, RuntimeError) as exc:
        return {"unavailable": str(exc)[:160] or "Property unavailable"}


def collection(obj, name, render, limit=8):
    result = {"items": [], "complete": False}
    try:
        values = getattr(obj, name)
        result["total"] = values.count
        for index in range(min(values.count, limit)):
            result["items"].append(render(values.item(index)))
        result.update(returned=len(result["items"]), complete=len(result["items"]) == values.count)
        if not result["complete"]:
            result["nextOffset"] = len(result["items"])
    except (AttributeError, RuntimeError) as exc:
        result["unavailable"] = str(exc)[:160] or "Collection unavailable"
    return result


def named(obj):
    return {"name": field(obj, "name")}


def health(obj):
    return {**named(obj), "healthState": field(obj, "healthState"),
            "message": field(obj, "errorOrWarningMessage")}


def design_summary(design):
    def component(obj):
        return {**named(obj), "bodies": collection(obj, "bRepBodies", named),
                "sketches": collection(obj, "sketches", lambda sketch: {
                    **named(sketch), "fullyConstrained": field(sketch, "isFullyConstrained")}),
                "features": collection(obj, "features", health),
                "occurrences": collection(obj, "occurrences", lambda occ: {
                    "path": field(occ, "fullPathName"), "suppressed": field(occ, "isSuppressed")})}
    return {"units": field(design.unitsManager, "defaultLengthUnits"),
            "components": collection(design, "allComponents", component, 6),
            "parameters": collection(design, "userParameters", lambda p: {
                **named(p), "expression": field(p, "expression"), "unit": field(p, "unit")}, 20)}


def cam_summary(cam):
    return {"setups": collection(cam, "setups", lambda setup: {
        **named(setup), "operationType": field(setup, "operationType"),
        "operations": collection(setup, "allOperations", lambda op: {
            **named(op), "hasToolpath": field(op, "hasToolpath"),
            "isToolpathValid": field(op, "isToolpathValid"), "isSuppressed": field(op, "isSuppressed")})})}


def electronics_summary(product):
    kind = product.objectType.rsplit("::", 1)[-1]
    fields = {"Schematic": ("sheets", "parts", "nets"),
              "Board": ("elements", "signals", "layers"),
              "Library": ("symbols", "packages", "deviceSets")}
    result = {"kind": kind, **named(product), "designEditing": "not_exposed",
              "guidance": "The documented Electronics Python API is a read-only preview for design content. "
                          "Check installed API help for specific operations and units; do not assume mechanical units.",
              "source": "https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ElectronicsIntro.htm"}
    for name in fields.get(kind, ()):
        result[name] = collection(product, name, named)
    if kind == "EcadDesign":
        for name in ("board", "schematic"):
            try:
                child = getattr(product, name)
                result[name] = named(child) if child is not None else None
            except (AttributeError, RuntimeError) as exc:
                result[name] = {"unavailable": str(exc)[:160]}
    return result
