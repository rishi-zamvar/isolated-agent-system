"""Cyclomatic complexity gate using stdlib ast (no radon dependency).

Score = 1 + number of decision points (if/for/while/except/bool-op extra
operands/comprehension-ifs/ternaries). A function over the ceiling fails."""

import ast

_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
           ast.IfExp, ast.comprehension)


def _score(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCH):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


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
