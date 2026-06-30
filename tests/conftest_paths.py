"""Load the hyphenated/script modules by path so tests can import their functions.

These scripts are meant to run standalone (a hook / a CLI), not be pip-installed, so
we load them from disk rather than as packages.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(relpath, name):
    path = os.path.join(ROOT, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


archive = load("scripts/archive_finished_queue.py", "engram_archive")
session_start = load("hooks/session-start.py", "engram_session_start")
