import pytest

from minitap.mobile_use.benchmark.text_check import (
    compare_text,
    find_focused_text_element,
    normalize_text,
)


def test_normalize():
    assert normalize_text("  a b\n\nc​ ") == "a b c"
    assert normalize_text("ｆｕｌｌ") == "full"  # NFKC
    assert normalize_text(None) == ""


@pytest.mark.parametrize(
    "expected,actual,verdict",
    [
        ("Hello world", "Hello world", "MATCH"),
        ("Hello world", "Hello  world\n", "MATCH"),
        ("line1\n\nline2", "line1 line2", "MATCH"),
        ("world", "Hello world", "CONTAINS"),
        ("hello", "Hello", "CASE_ONLY"),
        ("hello", "help", "MISMATCH"),
        ("hello", "", "MISMATCH"),
        ("hello", None, "UNVERIFIABLE"),
    ],
)
def test_verdicts(expected, actual, verdict):
    assert compare_text(expected, actual).verdict == verdict


def test_password_is_unverifiable():
    assert compare_text("secret", "••••••", is_password=True).verdict == "UNVERIFIABLE"


def test_feedback_mentions_both_values():
    fb = compare_text("abc", "abd").as_feedback()
    assert "MISMATCH" in fb and "'abc'" in fb and "'abd'" in fb
    assert "MATCH" in compare_text("abc", "abc").as_feedback()


def test_focused_element_prefers_edittext():
    ui = [
        {"class": "android.widget.Button", "focused": "true", "text": "x"},
        {"class": "android.widget.EditText", "focused": "true", "text": "typed"},
        {"class": "android.widget.EditText", "focused": "false", "text": "other"},
    ]
    assert find_focused_text_element(ui)["text"] == "typed"
    assert find_focused_text_element([]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch_as_error,expected_failed", [(False, False), (True, True)])
async def test_tool_side_check_records_event(tmp_path, mismatch_as_error, expected_failed):
    import json
    from types import SimpleNamespace

    from minitap.mobile_use.benchmark import runtime as rt
    from minitap.mobile_use.benchmark.text_check import TextCheckConfig
    from minitap.mobile_use.tools.mobile.focus_and_input_text import _run_text_match_check
    from minitap.mobile_use.tools.types import Target

    r = rt.BenchmarkRuntime(tmp_path / "e.jsonl", "r", rt.LLMPolicy())
    rt.activate(r)
    try:
        ctx = SimpleNamespace(
            text_check_config=TextCheckConfig(mismatch_as_error=mismatch_as_error)
        )
        feedback, failed = await _run_text_match_check(
            ctx=ctx,  # type: ignore[arg-type]
            text="Paris",
            target=Target(resource_id="id/city", resource_id_index=0),
            focus_method="resource_id",
            readback_element={"resource-id": "id/city", "text": "Pari"},
            readback_hierarchy=None,
        )
    finally:
        rt.deactivate()
    assert "MISMATCH" in feedback and failed is expected_failed
    ev = json.loads((tmp_path / "e.jsonl").read_text().splitlines()[-1])
    assert ev["type"] == "text_check" and ev["verdict"] == "MISMATCH"
    assert ev["expected"] == "Paris" and ev["actual"] == "Pari" and ev["match"] is False


def test_find_by_resource_id_accepts_both_hierarchy_formats():
    from minitap.mobile_use.benchmark.text_check import find_by_resource_id
    from minitap.mobile_use.utils.ui_hierarchy import find_element_by_resource_id

    ui = [
        {"resource-id": "android:id/search_src_text", "text": "first"},
        {"resource-id": "android:id/search_src_text", "text": "second"},
    ]
    assert find_by_resource_id(ui, "android:id/search_src_text")["text"] == "first"
    assert find_by_resource_id(ui, "android:id/search_src_text", 1)["text"] == "second"
    assert find_by_resource_id([{"resourceId": "x", "text": "m"}], "x")["text"] == "m"
    # Documents audit A10: the shared paper-era helper does not match UIAutomator2 elements.
    assert find_element_by_resource_id(ui, "android:id/search_src_text") is None
