"""Narrow mitigation for the observed native CAM probe-value crash, not a sandbox."""
from contextlib import contextmanager
import inspect

from .tool_protocol import ToolError


@contextmanager
def protect_cam_values(parameter_class, record):
    # Fusion's Python wrapper exposes this as a replaceable Python property. Only
    # replace it during EVE's main-thread script; restore it on every exit path.
    if parameter_class is None:
        yield
        return
    original = inspect.getattr_static(parameter_class, "value")
    if not isinstance(original, property) or original.fget is None:
        raise ToolError("cam_guard_unavailable", "The installed CAM value wrapper does not support EVE's crash guard.")

    def guarded_value(parameter):
        name = parameter.name
        frame = inspect.currentframe().f_back
        line = frame.f_lineno if frame.f_code.co_filename == "<EVE script>" else None
        del frame
        record("cam.parameter.read", parameter=name, member="value", line=line)
        # The native stack entered CadProbe while enumerating probe parameters.
        # We do not know which exact parameter failed: quarantine probe-related
        # typed values until verified, while leaving scalar expressions accessible.
        if "probe" in name.casefold():
            record("cam.parameter.blocked", parameter=name, member="value")
            raise ToolError("unsafe_cam_probe_value", f"Typed value access for CAM parameter {name!r} is temporarily blocked after a native Fusion probing crash.")
        value = original.fget(parameter)
        record("cam.parameter.read_completed", parameter=name, member="value")
        return value

    parameter_class.value = property(guarded_value, original.fset, original.fdel, original.__doc__)
    try:
        yield
    finally:
        parameter_class.value = original
