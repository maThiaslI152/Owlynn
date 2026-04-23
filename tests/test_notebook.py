"""Tests for the notebook (stateful REPL) tool."""
import sys
from unittest.mock import MagicMock
sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.notebook import notebook_run, notebook_reset, notebook_vars, _reset_notebook


@pytest.fixture(autouse=True)
def clean_notebook():
    _reset_notebook()
    yield
    _reset_notebook()


def test_simple_expression():
    result = notebook_run.invoke({"code": "print(2 + 2)"})
    assert "4" in result


def test_variable_persistence():
    notebook_run.invoke({"code": "x = 42"})
    result = notebook_run.invoke({"code": "print(x * 2)"})
    assert "84" in result


def test_import_persistence():
    notebook_run.invoke({"code": "import math"})
    result = notebook_run.invoke({"code": "print(math.pi)"})
    assert "3.14" in result


def test_error_handling():
    result = notebook_run.invoke({"code": "1 / 0"})
    assert "Error" in result or "ZeroDivision" in result


def test_reset():
    notebook_run.invoke({"code": "x = 100"})
    result = notebook_reset.invoke({})
    assert "reset" in result.lower()

    result = notebook_run.invoke({"code": "print(x)"})
    assert "Error" in result or "NameError" in result


def test_multiline():
    result = notebook_run.invoke({"code": "for i in range(3):\n    print(i)"})
    assert "0" in result
    assert "1" in result
    assert "2" in result


def test_cell_counter():
    r1 = notebook_run.invoke({"code": "1"})
    r2 = notebook_run.invoke({"code": "2"})
    assert "Cell 1" in r1
    assert "Cell 2" in r2
