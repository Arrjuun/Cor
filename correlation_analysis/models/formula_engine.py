"""Safe formula evaluation engine for derived sensor values."""
from __future__ import annotations

import ast
import math
from graphlib import TopologicalSorter, CycleError
from typing import Optional

import numpy as np
import pandas as pd


# Safe built-in namespace
_SAFE_NAMESPACE: dict = {
    "abs": abs,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "exp": math.exp,
    "min": min,
    "max": max,
    "round": round,
    "sum": sum,
    "nan": float("nan"),
    "pi": math.pi,
    # numpy versions for Series operations
    "np": np,
}

_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Expression,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd,
    ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Attribute, ast.Subscript, ast.Index, ast.Tuple, ast.List,
)


class FormulaError(Exception):
    """Raised when formula evaluation fails."""


class FormulaEngine:
    """
    Evaluates formulas referencing sensor names to produce derived Series.

    Sensor names are resolved from a namespace dict:
        {sensor_name: pd.Series(values, index=load_steps)}
    """

    def __init__(self) -> None:
        self._cache: dict[str, pd.Series] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(self, formula: str, namespace: dict[str, pd.Series]) -> pd.Series:
        """
        Evaluate a formula string using the given sensor namespace.

        Args:
            formula: Expression string, e.g. "(SensorA + SensorB) / 2"
            namespace: {sensor_name: pd.Series}

        Returns:
            pd.Series with result values indexed by load step.

        Raises:
            FormulaError on syntax or runtime errors.
        """
        self._validate_ast(formula)
        safe_ns = dict(_SAFE_NAMESPACE)
        safe_ns.update(namespace)  # sensor names shadow builtins intentionally

        try:
            result = eval(compile(ast.parse(formula, mode="eval"), "<formula>", "eval"),  # noqa: S307
                          {"__builtins__": {}}, safe_ns)
        except ZeroDivisionError as exc:
            raise FormulaError(f"Division by zero in formula: {formula}") from exc
        except NameError as exc:
            raise FormulaError(f"Unknown sensor name in formula: {exc}") from exc
        except Exception as exc:
            raise FormulaError(f"Error evaluating formula '{formula}': {exc}") from exc

        if isinstance(result, pd.Series):
            return result
        # Scalar – broadcast to match any series shape
        if namespace:
            ref_series = next(iter(namespace.values()))
            return pd.Series(result, index=ref_series.index)
        return pd.Series([result])

    def evaluate_all(
        self,
        formulas: dict[str, str],
        base_namespace: dict[str, pd.Series],
    ) -> dict[str, pd.Series]:
        """
        Evaluate multiple formulas in dependency order.

        Args:
            formulas: {derived_sensor_name: formula_string}
            base_namespace: {raw_sensor_name: pd.Series}

        Returns:
            {derived_sensor_name: pd.Series}

        Raises:
            FormulaError on circular dependency or evaluation error.
        """
        # Build dependency graph
        dep_graph: dict[str, set[str]] = {}
        all_known = set(base_namespace.keys()) | set(formulas.keys())
        for name, formula in formulas.items():
            refs = self._extract_names(formula)
            deps = refs & all_known - {name}
            dep_graph[name] = deps

        # Topological sort
        try:
            order = list(TopologicalSorter(dep_graph).static_order())
        except CycleError as exc:
            raise FormulaError(f"Circular dependency in formulas: {exc}") from exc

        ns = dict(base_namespace)
        results: dict[str, pd.Series] = {}
        for name in order:
            if name in formulas:
                results[name] = self.evaluate(formulas[name], ns)
                ns[name] = results[name]

        return results

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_ast(formula: str) -> None:
        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError as exc:
            raise FormulaError(f"Syntax error in formula: {exc}") from exc

        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                raise FormulaError(
                    f"Unsupported operation '{type(node).__name__}' in formula."
                )

    @staticmethod
    def _extract_names(formula: str) -> set[str]:
        """Extract all Name nodes from a formula string."""
        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError:
            return set()
        return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
