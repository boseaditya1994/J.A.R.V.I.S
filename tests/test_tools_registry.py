import pytest

from jarvis.tools import registry


def test_calculator_evaluates_basic_arithmetic():
    result = registry.CALCULATOR.handler({"expression": "2 + 3 * 4"})
    assert result == "14"


def test_calculator_handles_parentheses_and_division():
    result = registry.CALCULATOR.handler({"expression": "(10 - 4) / 2"})
    assert result == "3.0"


def test_calculator_rejects_name_lookup():
    with pytest.raises(ValueError):
        registry.CALCULATOR.handler({"expression": "__import__('os').system('dir')"})


def test_calculator_rejects_function_call():
    with pytest.raises(ValueError):
        registry.CALCULATOR.handler({"expression": "print(1)"})


def test_calculator_rejects_empty_expression():
    with pytest.raises(ValueError):
        registry.CALCULATOR.handler({"expression": ""})


def test_calculator_rejects_huge_exponent():
    with pytest.raises(ValueError):
        registry.CALCULATOR.handler({"expression": "9 ** 9 ** 9"})


def test_client_tools_returns_all_five_tools():
    names = {t.name for t in registry.client_tools()}
    assert names == {
        "calculator",
        "filesystem_read",
        "filesystem_write",
        "shell_execute",
        "knowledge_search",
    }


def test_client_tools_risk_levels():
    risks = {t.name: t.risk for t in registry.client_tools()}
    assert risks["calculator"] == "low"
    assert risks["filesystem_read"] == "low"
    assert risks["filesystem_write"] == "high"
    assert risks["shell_execute"] == "critical"
    assert risks["knowledge_search"] == "low"


def test_to_api_schema_shape():
    schema = registry.to_api_schema(registry.CALCULATOR)
    assert set(schema.keys()) == {"name", "description", "input_schema"}
    assert schema["name"] == "calculator"


def test_find_tool_returns_none_for_unknown_name():
    assert registry.find_tool("nonexistent_tool") is None


def test_find_tool_finds_each_client_tool():
    for name in (
        "calculator",
        "filesystem_read",
        "filesystem_write",
        "shell_execute",
        "knowledge_search",
    ):
        assert registry.find_tool(name) is not None
        assert registry.find_tool(name).name == name


def test_web_search_tool_dict_variant_by_complexity():
    assert registry.web_search_tool_dict("normal")["type"] == "web_search_20250305"
    assert registry.web_search_tool_dict("high")["type"] == "web_search_20260209"


def test_web_fetch_tool_dict_variant_by_complexity():
    normal = registry.web_fetch_tool_dict("normal")
    high = registry.web_fetch_tool_dict("high")

    assert normal["type"] == "web_fetch_20250910"
    assert high["type"] == "web_fetch_20260209"
    assert normal["citations"]["enabled"] is True
    assert high["citations"]["enabled"] is True
