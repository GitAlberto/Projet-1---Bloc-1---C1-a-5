"""Points d'entree de la phase de collecte du pipeline."""

from importlib import import_module

_collect_module = import_module(f"{__name__}.1_collecter")

run_collection = _collect_module.run_collection

__all__ = ["run_collection"]
