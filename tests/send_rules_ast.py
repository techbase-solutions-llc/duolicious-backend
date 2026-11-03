"""Shared AST helpers for the send rules (send safeguards plan, 2 Nov 2026,
task 2). Standard library only: the deploy's `rules` job runs these tests on
a bare GitHub runner with nothing but pytest and pyyaml installed, and
imports no app module."""
from __future__ import annotations

import ast
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]

_SKIP_DIRS = frozenset({'tests', '.worktrees', 'node_modules', 'venv', '.venv', '.git', '__pycache__',
                        '.claude', 'test'})


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def files(suffixes: tuple[str, ...]) -> Iterator[Path]:
    """Every file of these types in the repo, outside tests and checkouts.
    A module named test_*.py beside the code it tests is a test too."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(suffixes) and not (name.startswith('test_') and name.endswith('.py')):
                yield Path(dirpath) / name


def py_files() -> Iterator[Path]:
    return files(('.py',))


@lru_cache(maxsize=None)
def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def imports(tree: ast.AST, modname: str = '') -> Iterator[tuple[str, Optional[str]]]:
    """(module, name) for every import anywhere in the tree, functions
    included. `import a.b` gives ('a.b', None); `from a import b` gives
    ('a', 'b'). Relative imports are resolved against `modname`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, None
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                pkg = modname.split('.')
                pkg = pkg[:len(pkg) - node.level + (1 if _is_package(modname) else 0)]
                base = '.'.join(pkg + ([base] if base else []))
            for a in node.names:
                yield base, a.name


def _is_package(modname: str) -> bool:
    return (ROOT / Path(*modname.split('.')) / '__init__.py').is_file() if modname else False


def calls(tree: ast.AST) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def call_name(call: ast.Call) -> str:
    """`a.b.c(...)` -> 'a.b.c'; `f(...)` -> 'f'."""
    parts = []
    f = call.func
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return '.'.join(reversed(parts))


def names_used(tree: ast.AST) -> Iterator[str]:
    """Every bare name and attribute name in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
