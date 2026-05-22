"""Flask-калькулятор.

Маршруты:
    GET  /calculator      — HTML-интерфейс (templates/calculator.html)
    POST /api/calculate   — JSON API для вычислений

Запуск:
    python calculator.py
    (порт 5050, не конфликтует с dashboard на :4999)
"""

from __future__ import annotations

import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# calculator.py живёт в корне репо; templates/ — там же, но Flask ищет
# templates относительно instance_path / root_path. Указываем явно.
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = Flask(__name__, template_folder=str(_TEMPLATES_DIR))

# Белый список: цифры, операторы, точка, скобки, пробел
_SAFE_PATTERN = re.compile(r"^[0-9+\-*/().\s]+$")


def _evaluate(expression: str) -> float | int:
    """Вычисляет выражение после проверки белого списка.

    Returns:
        Числовой результат.

    Raises:
        ValueError: если выражение содержит недопустимые символы или синтаксически неверно.
        ZeroDivisionError: при делении на ноль.
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("empty expression")
    if not _SAFE_PATTERN.fullmatch(expr):
        raise ValueError("invalid characters in expression")
    try:
        result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
    except ZeroDivisionError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid expression: {exc}") from exc
    if not isinstance(result, (int, float)):
        raise ValueError("expression did not evaluate to a number")
    return result


@app.route("/calculator", methods=["GET"])
def calculator_page():
    """Возвращает HTML-интерфейс калькулятора."""
    return render_template("calculator.html")


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """Вычисляет математическое выражение.

    Входной JSON: {"expression": "<строка>"}
    Ответ 200:    {"result": <число>}
    Ответ 400:    {"error": "<описание>"}
    """
    data = request.get_json(silent=True)
    if not data or "expression" not in data:
        return jsonify({"error": "missing 'expression' field"}), 400

    expression = data["expression"]
    if not isinstance(expression, str):
        return jsonify({"error": "'expression' must be a string"}), 400

    try:
        result = _evaluate(expression)
    except ZeroDivisionError:
        return jsonify({"error": "division by zero"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Возвращаем int если результат целый, иначе float
    if isinstance(result, float) and result.is_integer():
        result = int(result)

    return jsonify({"result": result}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5050)
