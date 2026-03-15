"""Formula syntax validation using the ast module."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of formula validation."""
    is_valid: bool
    error_message: str = ""
    referenced_sensors: list[str] = field(default_factory=list)


# Allowed AST node types for safe formula evaluation
_ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd,
    ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Subscript, ast.Index,
    ast.Attribute,
    ast.Tuple, ast.List,
)

_ALLOWED_FUNCTIONS = {
    "abs", "sqrt", "sin", "cos", "tan", "log", "exp",
    "min", "max", "round", "sum",
}


class FormulaValidator:
    """Validates formula expressions against a set of known sensor names."""

    def __init__(self, sensor_names: list[str] | None = None):
        self.sensor_names: set[str] = set(sensor_names or [])

    def validate(self, formula: str) -> ValidationResult:
        """Validate a formula string."""
        if not formula.strip():
            return ValidationResult(is_valid=False, error_message="Formula is empty.")

        # Replace $SensorName with _sensor_ for AST parsing
        parse_formula = formula
        referenced: list[str] = []

        try:
            tree = ast.parse(parse_formula, mode="eval")
        except SyntaxError as exc:
            return ValidationResult(is_valid=False, error_message=f"Syntax error: {exc}")

        # Walk nodes and validate
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Unsupported operation in formula: {type(node).__name__}",
                )
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name not in _ALLOWED_FUNCTIONS:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Function '{func_name}' is not allowed.",
                    )
            if isinstance(node, ast.Name):
                name = node.id
                if name in self.sensor_names:
                    referenced.append(name)

        return ValidationResult(
            is_valid=True,
            referenced_sensors=list(set(referenced)),
        )
