"""P2 F2: safe deterministic arithmetic for counts, sums, products, durations and unit
conversions (LLM mental arithmetic and rounding were a failure source)."""

from __future__ import annotations

import ast
import math
import operator

_LENGTH_M = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
    "cm": 0.01, "mm": 0.001, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254, "nmi": 1852.0,
}
_TIME_S = {
    "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0, "min": 60.0, "minute": 60.0,
    "minutes": 60.0, "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "day": 86400.0, "days": 86400.0, "week": 604800.0, "weeks": 604800.0,
}
_MASS_KG = {
    "kg": 1.0, "g": 0.001, "mg": 1e-6, "lb": 0.45359237, "lbs": 0.45359237, "oz": 0.028349523125,
}


def convert(value: float, from_unit: str, to_unit: str) -> float:
    f, t = from_unit.strip().lower(), to_unit.strip().lower()
    for table in (_LENGTH_M, _TIME_S, _MASS_KG):
        if f in table and t in table:
            return value * table[f] / table[t]
    if {f, t} <= {"c", "f", "celsius", "fahrenheit"}:
        if f[0] == t[0]:
            return value
        return value * 9 / 5 + 32 if f[0] == "c" else (value - 32) * 5 / 9
    raise ValueError(f"cannot convert {from_unit!r} to {to_unit!r}")


def seconds(duration: str) -> int:
    """'1:02:03' / '02:03' / '45' -> seconds."""
    parts = [int(p) for p in str(duration).strip().split(":")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def hms(total_seconds: float) -> str:
    s = int(round(total_seconds))
    sign = "-" if s < 0 else ""
    s = abs(s)
    return f"{sign}{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "round": round, "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil, "prod": math.prod,
    "convert": convert, "seconds": seconds, "hms": hms,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float | str):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return _UNOPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.List | ast.Tuple):
        return [_eval(e) for e in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"unsupported expression element: {ast.dump(node)[:80]}")


def calculate(expression: str):
    if len(expression) > 2000:
        raise ValueError("expression too long")
    return _eval(ast.parse(expression.strip(), mode="eval"))
