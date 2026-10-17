import pytest

from orgraph.engine.templating import TemplateError, render

CTX = {
    "input": {"channel": "#eng", "count": 3, "tags": ["a", "b"], "nested": {"ok": True}},
    "run": {"id": "r1", "started_at": "2026-01-01T00:00:00.000Z"},
    "tasks": {
        "find": {"status": "succeeded", "output": {"issues": [{"key": "ENG-1"}, {"key": "ENG-2"}]}}
    },
}


def test_plain_values_pass_through():
    assert render("hello", CTX) == "hello"
    assert render(5, CTX) == 5
    assert render(None, CTX) is None
    assert render(True, CTX) is True


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{{ input.channel }}", "#eng"),
        ("{{input.count}}", 3),
        ("{{ input.tags }}", ["a", "b"]),
        ("{{ input.nested }}", {"ok": True}),
        ("{{ input.nested.ok }}", True),
        ("{{ tasks.find.output.issues.0.key }}", "ENG-1"),
        ("{{ tasks.find.output.issues.1 }}", {"key": "ENG-2"}),
        ("{{ run.id }}", "r1"),
    ],
)
def test_single_expression_keeps_type(template, expected):
    assert render(template, CTX) == expected


def test_mixed_string_interpolates_text():
    assert render("post to {{ input.channel }} x{{ input.count }}", CTX) == "post to #eng x3"


def test_mixed_string_json_encodes_non_strings():
    assert render("tags={{ input.tags }} n={{ input.nested }}", CTX) == (
        'tags=["a", "b"] n={"ok": true}'
    )


def test_two_expressions_are_not_a_single_expression():
    assert render("{{ input.count }}{{ input.count }}", CTX) == "33"


def test_surrounding_text_makes_it_text():
    assert render(" {{ input.count }}", CTX) == " 3"


def test_recurses_into_dicts_and_lists():
    value = {"a": ["{{ input.count }}", {"b": "{{ run.id }}"}], "{{ run.id }}": 1}
    assert render(value, CTX) == {"a": [3, {"b": "r1"}], "{{ run.id }}": 1}


def test_does_not_mutate_input():
    value = {"a": ["{{ input.count }}"]}
    render(value, CTX)
    assert value == {"a": ["{{ input.count }}"]}


@pytest.mark.parametrize(
    "expr",
    [
        "input.missing",
        "tasks.find.output.issues.5.key",
        "tasks.find.output.issues.x",
        "input.channel.deeper",
        "nope",
        "",
        "input..count",
        "tasks.find.output.issues.-1",
    ],
)
def test_unresolvable_expression_names_itself(expr):
    with pytest.raises(TemplateError) as exc:
        render("{{ " + expr + " }}", CTX)
    assert expr in str(exc.value)


def test_unresolvable_inside_mixed_string():
    with pytest.raises(TemplateError, match="input.missing"):
        render("hi {{ input.missing }}", CTX)


def test_resolved_values_are_not_rendered_again():
    assert render("{{ input.t }}", {"input": {"t": "{{ input.x }}"}}) == "{{ input.x }}"


def test_no_attribute_access_or_eval():
    with pytest.raises(TemplateError):
        render("{{ input.__class__ }}", CTX)
    with pytest.raises(TemplateError):
        render("{{ 1 + 1 }}", CTX)
