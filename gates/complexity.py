"""Cyclomatic complexity gate using stdlib ast (no radon dependency).

Score = 1 + number of decision points (if/for/while/except/bool-op extra
operands/comprehension-ifs/ternaries). A function over the ceiling fails."""

import ast

_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
           ast.IfExp, ast.comprehension)


def _decision_points(node: ast.AST) -> int:
    """Count decision points in `node`'s own body, NOT descending into nested
    function/lambda bodies — those are scored as their own functions, so absorbing
    their branches double-counts (a CC=1 wrapper around a CC=11 closure read as 11)."""
    total = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, _BRANCH):
            total += 1
        elif isinstance(child, ast.BoolOp):
            total += len(child.values) - 1
        total += _decision_points(child)
    return total


def _score(node: ast.AST) -> int:
    return 1 + _decision_points(node)


def score_functions(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _score(node)
    return out


def gate(source: str, ceiling: int) -> list[tuple[str, int]]:
    """Return (name, score) for every function whose score exceeds the ceiling."""
    return [(n, s) for n, s in score_functions(source).items() if s > ceiling]
