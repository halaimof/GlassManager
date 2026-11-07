"""Безопасное вычисление параметрических формул: «L / 2 + 30», «min(A, 900)»."""
from __future__ import annotations

import ast
import math
import operator

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "sqrt": math.sqrt,
}


class FormulaError(ValueError):
    pass


def eval_formula(expr: str | float | int, variables: dict[str, float]) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    text = str(expr).strip()
    if not text:
        raise FormulaError("Пустая формула")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Ошибка в формуле «{text}»") from e

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name):
            if node.id in variables:
                return float(variables[node.id])
            raise FormulaError(f"Неизвестная переменная «{node.id}» в формуле «{text}»")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return float(_FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise FormulaError(f"Недопустимое выражение в формуле «{text}»")

    try:
        return ev(tree)
    except ZeroDivisionError as e:
        raise FormulaError(f"Деление на ноль в формуле «{text}»") from e
