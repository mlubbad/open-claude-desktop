"""
Sample Open Claude Desktop plugin — a safe arithmetic calculator.

A plugin is any plugins/*.py module that defines:
  NAME         : str   — unique tool name
  DESCRIPTION  : str   — shown in the Plugins menu
  TOOL         : dict  — an OpenAI/GLM tool schema (function name == NAME)
  run(args)    : str   — executes the tool call and returns a string result

Enabled plugins are exposed to the BigQuery agent as additional tools.
"""
import ast
import operator

NAME = "calculator"
DESCRIPTION = "Evaluate a basic arithmetic expression."

TOOL = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression, e.g. '2*(3+4)/5'. "
                       "Supports + - * / ** % and parentheses.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string",
                               "description": "The arithmetic expression."}},
            "required": ["expression"],
        },
    },
}

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Unsupported expression.")


def run(args: dict) -> str:
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return "No expression provided."
    try:
        result = _eval(ast.parse(expr, mode="eval").body)
        return f"{expr} = {result}"
    except Exception as e:
        return f"Could not evaluate '{expr}': {e}"
