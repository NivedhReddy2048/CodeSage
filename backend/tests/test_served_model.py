"""What actually served each call, and the schema each agent's output is held to.

Issue #51: after a Groq -> Gemini failover every run was stamped with the Groq
model it had asked for, so the comment, the cost estimate and the analytics all
described a model that never ran. And Gemini was held to the findings schema for
every agent, so the intent classifier and the grounding agent could not answer
their own questions on the fallback path.
"""

import json
from unittest import mock

import pytest

from apps.agents import breaker as breaker_module
from apps.agents import static_analysis
from apps.agents.graph import Runtime, run_pipeline
from apps.agents.providers import GeminiProvider, GroqProvider, ProviderError, ProviderResponse
from apps.agents.schema import (
    GROUNDING_SCHEMA,
    INTENT_SCHEMA,
    RESPONSE_SCHEMA,
    to_gemini_schema,
)
from apps.agents.types import RepoContext, RetrievedChunk, ReviewConfig

DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -10,6 +10,8 @@ def helper():
 def paginate_users(users, page, per_page=10):
     start = (page - 1) * per_page
-    end = start + per_page
+    end = page + per_page
+    query = "SELECT * FROM users WHERE name = '%s'" % users
     return users[start:end]
"""

FALLBACK = "gemini-flash-lite-latest"


def config():
    return ReviewConfig(
        groq_api_key="groq-test",
        gemini_api_key="gemini-test",
        backoff_seconds=0.0,
        max_retries=1,
        fallback_model=FALLBACK,
    )


@pytest.fixture(autouse=True)
def clean_breakers():
    breaker_module.reset_all()
    yield
    breaker_module.reset_all()


def groq_down(self, system_prompt, messages, schema=None):
    raise ProviderError("groq: HTTP 401: invalid api key")


def gemini_answers(seen):
    """A Gemini stand-in that answers in whatever shape the schema asks for."""

    def _complete(self, system_prompt, messages, schema=None):
        seen.append(schema)
        properties = (schema or RESPONSE_SCHEMA)["properties"]
        if "intent" in properties:
            content = {"intent": "fix", "summary": "Changes pagination."}
        elif "cited_file" in properties["findings"]["items"]["properties"]:
            content = {
                "findings": [
                    {
                        "file": "app/users.py",
                        "line": 13,
                        "severity": "nit",
                        "category": "correctness",
                        "message": "paginate_users duplicates the existing helper.",
                        "cited_file": "app/pagination.py",
                        "cited_line": 3,
                    }
                ]
            }
        else:
            content = {"findings": []}
        # No `model` set: the runtime must fill in the provider's own model.
        return ProviderResponse(json.dumps(content), input_tokens=100, output_tokens=20)

    return _complete


def retrieve(query):
    return [
        RetrievedChunk(
            file_path="app/pagination.py",
            symbol="paginate_users",
            line_start=1,
            line_end=6,
            content="def paginate_users(items, page, per_page=10):\n    return items\n",
        )
    ]


def test_the_runtime_reports_the_model_that_served_a_failover():
    seen = []
    with (
        mock.patch.object(GroqProvider, "complete", groq_down),
        mock.patch.object(GeminiProvider, "complete", gemini_answers(seen)),
    ):
        response, provider, used_fallback = Runtime(config()).complete(
            "openai/gpt-oss-20b", "system", "message", schema=INTENT_SCHEMA
        )

    assert (provider, used_fallback) == ("gemini", True)
    assert response.model == FALLBACK
    assert seen == [INTENT_SCHEMA]


@pytest.mark.django_db
def test_runs_served_by_the_fallback_never_carry_the_primary_model_name():
    seen = []
    with (
        mock.patch.object(GroqProvider, "complete", groq_down),
        mock.patch.object(GeminiProvider, "complete", gemini_answers(seen)),
        mock.patch(
            "apps.agents.nodes.run_analysis",
            return_value=static_analysis.AnalysisReport(ran=["ruff", "bandit"]),
        ),
    ):
        result = run_pipeline(
            DIFF, RepoContext(full_name="o/r", pr_number=1), config(), retrieve=retrieve
        )

    llm_runs = [run for run in result.agent_runs if run.requested_model]
    assert {run.name for run in llm_runs} == {
        "diff_intent",
        "security",
        "grounding",
        "test_coverage",
    }
    for run in llm_runs:
        assert run.succeeded, (run.name, run.error)
        assert run.model == FALLBACK, run.name
        assert run.provider == "gemini"
        assert run.used_fallback
        assert run.requested_model.startswith("openai/gpt-oss-")

    assert result.model_used == FALLBACK
    assert {call.model for call in result.calls} == {FALLBACK}
    assert "gpt-oss" not in result.model_used


@pytest.mark.django_db
def test_each_agent_holds_the_fallback_to_its_own_schema():
    """The fix for the five-token diff_intent: it was being forced into findings."""
    seen = []
    with (
        mock.patch.object(GroqProvider, "complete", groq_down),
        mock.patch.object(GeminiProvider, "complete", gemini_answers(seen)),
        mock.patch(
            "apps.agents.nodes.run_analysis",
            return_value=static_analysis.AnalysisReport(ran=["ruff"]),
        ),
    ):
        result = run_pipeline(
            DIFF, RepoContext(full_name="o/r", pr_number=1), config(), retrieve=retrieve
        )

    assert INTENT_SCHEMA in seen
    assert GROUNDING_SCHEMA in seen
    assert seen.count(RESPONSE_SCHEMA) == 2  # security and test coverage

    by_name = {run.name: run for run in result.agent_runs}
    assert by_name["diff_intent"].succeeded
    # The grounding finding survives the citation check because the schema let
    # the fallback model emit its citation at all.
    assert by_name["grounding"].findings_count == 1


def test_an_intent_reply_with_nothing_usable_is_a_failure_with_a_reason():
    def empty(self, system_prompt, messages, schema=None):
        return ProviderResponse('{"findings": []}', input_tokens=100, output_tokens=5)

    from apps.agents.diffs import prepare
    from apps.agents.nodes import diff_intent

    with mock.patch.object(GroqProvider, "complete", empty):
        out = diff_intent(
            {
                "runtime": Runtime(config()),
                "prepared": prepare(DIFF, 24000),
                "context": RepoContext(full_name="o/r", pr_number=1),
            }
        )

    run = out["runs"][0]
    assert run.succeeded is False
    assert run.error.startswith("schema:")


def test_the_gemini_request_uses_native_json_mode_with_the_agents_schema():
    captured = {}

    def fake_post(url, timeout, **kwargs):
        captured.update(kwargs)
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"intent": "fix", "summary": "s"}'}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4},
        }
        return response

    provider = GeminiProvider(api_key="k", model=FALLBACK, max_retries=1)
    with mock.patch("apps.agents.providers.requests.post", side_effect=fake_post):
        response = provider.complete("sys", [{"role": "user", "content": "hi"}], INTENT_SCHEMA)

    generation = captured["json"]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseSchema"] == to_gemini_schema(INTENT_SCHEMA)
    assert generation["responseSchema"]["properties"]["intent"]["type"] == "STRING"
    assert response.model == FALLBACK


def test_the_gemini_schema_dialect_is_complete_and_keeps_citations():
    converted = to_gemini_schema(GROUNDING_SCHEMA)

    assert "additionalProperties" not in json.dumps(converted)
    item = converted["properties"]["findings"]["items"]
    assert item["type"] == "OBJECT"
    assert item["properties"]["cited_line"]["type"] == "INTEGER"
    assert {"cited_file", "cited_line"} <= set(item["required"])
    # The source schema is not mutated by the conversion.
    assert "additionalProperties" in GROUNDING_SCHEMA["properties"]["findings"]["items"]
