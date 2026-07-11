"""Repo-root pytest bootstrap.

The repo has a top-level `data/` directory, and the installed package inside it is
also called `data` (data/data/). With the repo root on sys.path, `import data`
resolves to the *folder* as a PEP-420 namespace package — so `data.graph` becomes
the `data/graph/` cypher-resources directory instead of the `data.graph` driver
module, and every suite fails to collect with "unknown location".

Dropping the repo root from sys.path makes `import data` resolve to the installed
veritas-data package, which is what every other entrypoint already gets.
"""
import pathlib
import sys

_ROOT = str(pathlib.Path(__file__).parent.resolve())
sys.path[:] = [p for p in sys.path if p not in ("", ".", _ROOT)]
