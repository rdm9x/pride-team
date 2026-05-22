"""Тесты для calculator.py — Flask-калькулятор.

Покрытие: _evaluate(), GET /calculator, POST /api/calculate.
Запуск: python -m pytest tests/test_calculator.py -v
"""

from __future__ import annotations

import importlib
import sys
import types
import pytest


# ---------------------------------------------------------------------------
# Фикстура: Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Создаёт тестовый клиент Flask без запуска реального сервера."""
    # Импортируем модуль из корня репо
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    import calculator as calc_module
    calc_module.app.config["TESTING"] = True
    with calc_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Тесты _evaluate()
# ---------------------------------------------------------------------------

class TestEvaluate:
    """Unit-тесты внутренней функции _evaluate."""

    def _fn(self):
        import os, sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from calculator import _evaluate
        return _evaluate

    def test_simple_addition(self):
        assert self._fn()("2+2") == 4

    def test_multiplication_with_parens(self):
        assert self._fn()("3*(4+2)") == 18

    def test_subtraction(self):
        assert self._fn()("10 - 3") == 7

    def test_division(self):
        result = self._fn()("10/4")
        assert result == 2.5

    def test_float_expression(self):
        result = self._fn()("1.5 + 2.5")
        assert result == 4.0

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            self._fn()("1/0")

    def test_empty_expression(self):
        with pytest.raises(ValueError, match="empty expression"):
            self._fn()("")

    def test_invalid_chars(self):
        with pytest.raises(ValueError, match="invalid characters"):
            self._fn()("__import__('os')")

    def test_invalid_syntax(self):
        with pytest.raises(ValueError, match="invalid expression"):
            self._fn()("2 2")  # два числа без оператора — SyntaxError

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="empty expression"):
            self._fn()("   ")

    def test_nested_parens(self):
        assert self._fn()("(2+3)*(10-4)") == 30

    def test_large_number(self):
        assert self._fn()("1000000 * 1000000") == 1_000_000_000_000


# ---------------------------------------------------------------------------
# Тесты GET /calculator
# ---------------------------------------------------------------------------

class TestCalculatorPage:
    def test_get_returns_200(self, client):
        resp = client.get("/calculator")
        assert resp.status_code == 200

    def test_get_returns_html(self, client):
        resp = client.get("/calculator")
        assert b"html" in resp.data.lower()


# ---------------------------------------------------------------------------
# Тесты POST /api/calculate
# ---------------------------------------------------------------------------

class TestApiCalculate:
    def test_basic_sum(self, client):
        resp = client.post("/api/calculate", json={"expression": "2+2"})
        assert resp.status_code == 200
        assert resp.get_json() == {"result": 4}

    def test_complex_expression(self, client):
        resp = client.post("/api/calculate", json={"expression": "3*(4+2)"})
        assert resp.status_code == 200
        assert resp.get_json() == {"result": 18}

    def test_division_by_zero_returns_400(self, client):
        resp = client.post("/api/calculate", json={"expression": "5/0"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "division by zero"

    def test_invalid_expression_returns_400(self, client):
        resp = client.post("/api/calculate", json={"expression": "abc"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_missing_field_returns_400(self, client):
        resp = client.post("/api/calculate", json={"foo": "bar"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_empty_body_returns_400(self, client):
        resp = client.post(
            "/api/calculate",
            data="not-json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_expression_not_string_returns_400(self, client):
        resp = client.post("/api/calculate", json={"expression": 42})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_float_result(self, client):
        resp = client.post("/api/calculate", json={"expression": "1/4"})
        assert resp.status_code == 200
        assert resp.get_json() == {"result": 0.25}

    def test_subtraction(self, client):
        resp = client.post("/api/calculate", json={"expression": "100 - 55"})
        assert resp.status_code == 200
        assert resp.get_json() == {"result": 45}

    def test_injection_attempt_rejected(self, client):
        resp = client.post(
            "/api/calculate", json={"expression": "__import__('os').system('id')"}
        )
        assert resp.status_code == 400

    def test_empty_expression_returns_400(self, client):
        resp = client.post("/api/calculate", json={"expression": ""})
        assert resp.status_code == 400

    def test_integer_result_for_whole_float(self, client):
        """10/2 = 5.0 -> должен вернуться int 5."""
        resp = client.post("/api/calculate", json={"expression": "10/2"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"result": 5}
        assert isinstance(data["result"], int)
