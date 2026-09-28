"""Explicit acceptance-only process interruption hooks, inert by default."""
import os


def hit(point: str) -> None:
    if os.environ.get("KAMMI_ACCEPTANCE_FAULTS") == "1" and os.environ.get("KAMMI_FAULT_POINT") == point:
        os._exit(91)
