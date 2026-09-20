"""Observability tests: one match = one trace with a fixed arbiter.* schema.

Uses an in-memory OTel span exporter attached to the global tracer provider
(Logfire configures it at import). No network, no sandbox, no real LLM:
scripted agents drive Engine tool spans, and a FunctionModel drives real
Pydantic AI agent-run/chat spans offline.
"""

import unittest

from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from app.agents.models import AgentType
from app.agents.prisoner import PrisonerAgent
from app.agents.tools import ToolCall, ToolResult
from app.agents.warden import WardenAgent
from app.engine import Engine
from app.observability import (
    agent_observability_context,
    match_span,
    output_telemetry,
)
from app.sandbox.models import ChallengeSpec


class FakeSandboxManager:
    def set_event_handler(self, match_id: str, handler: object) -> None:
        pass

    async def get_or_create_sandbox(self, match_id: str, config: object) -> object:
        return (match_id, config)

    async def destroy_sandbox(self, match_id: str) -> None:
        pass

    async def run_command(self, **kwargs: object) -> ToolResult:
        if kwargs.get("command") == "fail":
            return ToolResult(success=False, output="", error="boom", exit_code=1)
        return ToolResult(success=True, output="ok")

    async def read_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="file-contents")

    async def write_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="wrote")

    async def write_to_scratchpad(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="noted")

    async def watch_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="watching")


def _text_model() -> FunctionModel:
    def fn(messages: list[ModelMessage], info: object) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="done")])

    return FunctionModel(fn)


class SpanHelper:
    def __init__(self, exporter: InMemorySpanExporter) -> None:
        self.exporter = exporter

    def spans(self):  # type: ignore[no-untyped-def]
        return list(self.exporter.get_finished_spans())

    def clear(self) -> None:
        self.exporter.clear()

    def arbiter_spans(self, span_type: str):  # type: ignore[no-untyped-def]
        return [
            s
            for s in self.spans()
            if dict(s.attributes or {}).get("arbiter.span_type") == span_type
        ]

    def attrs(self, span) -> dict:  # type: ignore[no-untyped-def]
        return dict(span.attributes or {})


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        trace.get_tracer_provider().add_span_processor(
            SimpleSpanProcessor(self.exporter)
        )
        self.spans = SpanHelper(self.exporter)

    def make_engine(
        self, match_id: str = "obs-match", cooldown_seconds: float = 0
    ) -> Engine:
        return Engine(
            match_id=match_id,
            challenge=ChallengeSpec(
                name="obs-challenge",
                description="d",
                flag={"value": "ARB{obs}"},
            ),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
            cooldown_seconds=cooldown_seconds,
        )

    # -- match span ----------------------------------------------------

    async def test_match_creates_single_root_span_with_lifecycle(self) -> None:
        engine = self.make_engine()
        prisoner = PrisonerAgent(
            model_name="laguna-xs-2.1",
            objective="o",
            scripted_calls=[ToolCall(name="bash", arguments={"command": "id"})],
        )
        warden = WardenAgent(
            model_name="laguna-xs-2.1", objective="o", scripted_calls=[]
        )
        await engine.run_agents(prisoner, warden, timeout_seconds=0.3)

        matches = self.spans.arbiter_spans("match")
        self.assertEqual(len(matches), 1)
        match = matches[0]
        attrs = self.spans.attrs(match)
        self.assertIsNone(match.parent)
        self.assertEqual(attrs["arbiter.match_id"], "obs-match")
        self.assertEqual(attrs["arbiter.challenge_id"], "obs-challenge")
        self.assertEqual(attrs["arbiter.status"], "finished")
        self.assertEqual(attrs["arbiter.winner"], "warden")
        self.assertEqual(attrs["arbiter.end_reason"], "match timeout")
        self.assertIsNotNone(match.start_time)
        self.assertIsNotNone(match.end_time)
        self.assertGreaterEqual(match.end_time, match.start_time)

        # Everything for the match stays in one trace; tool spans are
        # descendants of the match span.
        trace_ids = {s.context.trace_id for s in self.spans.spans()}
        self.assertEqual(len(trace_ids), 1)
        match_id = format(match.context.span_id, "016x")
        tools = self.spans.arbiter_spans("tool")
        self.assertTrue(tools)
        by_id = {format(s.context.span_id, "016x"): s for s in self.spans.spans()}
        for tool in tools:
            self.assertIsNotNone(tool.parent)
            ancestor = tool
            seen_match = False
            while ancestor.parent is not None:
                ancestor = by_id[format(ancestor.parent.span_id, "016x")]
                if format(ancestor.context.span_id, "016x") == match_id:
                    seen_match = True
                    break
            self.assertTrue(seen_match, f"tool span {tool.name} outside match span")

    # -- tool spans: success / failure result --------------------------

    async def test_tool_span_success(self) -> None:
        engine = self.make_engine()
        await engine.start()
        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        self.assertTrue(result.success)

        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.match_id"], "obs-match")
        self.assertEqual(attrs["arbiter.agent_role"], "prisoner")
        self.assertEqual(attrs["arbiter.tool_name"], "bash")
        self.assertEqual(attrs["arbiter.status"], "executed")
        self.assertTrue(attrs["arbiter.success"])
        self.assertEqual(attrs["arbiter.credits_charged"], 2)
        self.assertGreater(attrs["arbiter.output_size"], 0)
        self.assertFalse(attrs["arbiter.output_truncated"])
        self.assertNotIn("arbiter.failure_category", attrs)

    async def test_tool_span_failed_result_is_executed_not_rejected(self) -> None:
        engine = self.make_engine()
        await engine.start()
        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "fail"})
        )
        self.assertFalse(result.success)

        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.status"], "executed")
        self.assertFalse(attrs["arbiter.success"])
        self.assertNotIn("arbiter.failure_category", attrs)

    # -- tool spans: rejections ----------------------------------------

    async def test_tool_span_rejections_carry_failure_category(self) -> None:
        engine = self.make_engine()
        await engine.start()

        cases = [
            (AgentType.PRISONER, ToolCall(name="nope", arguments={}), "tool_not_found"),
            (
                AgentType.PRISONER,
                ToolCall(name="watch_file", arguments={"path": "/x"}),
                "tool_not_allowed",
            ),
        ]
        for actor, call, category in cases:
            with self.subTest(category=category):
                self.spans.clear()
                result = await engine.execute_tool_call(actor, call)
                self.assertFalse(result.success)
                tools = self.spans.arbiter_spans("tool")
                self.assertEqual(len(tools), 1)
                attrs = self.spans.attrs(tools[0])
                self.assertEqual(attrs["arbiter.status"], "rejected")
                self.assertFalse(attrs["arbiter.success"])
                self.assertEqual(attrs["arbiter.failure_category"], category)
                self.assertEqual(attrs["arbiter.tool_name"], call.name)
                self.assertEqual(attrs["arbiter.agent_role"], actor.value)

    async def test_tool_span_rejection_cooldown(self) -> None:
        engine = self.make_engine("cooldown-match", cooldown_seconds=60.0)
        await engine.start()
        first = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        self.assertTrue(first.success)
        self.spans.clear()
        second = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        self.assertFalse(second.success)
        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.status"], "rejected")
        self.assertEqual(attrs["arbiter.failure_category"], "cooldown")

    async def test_tool_span_rejection_insufficient_credits(self) -> None:
        engine = self.make_engine()
        await engine.start()
        engine.state.prisoner.credits = 0
        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        self.assertFalse(result.success)
        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.status"], "rejected")
        self.assertEqual(attrs["arbiter.failure_category"], "insufficient_credits")

    async def test_tool_span_rejection_match_not_running(self) -> None:
        engine = self.make_engine()
        # Never started: status is CREATED, not RUNNING.
        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        self.assertFalse(result.success)
        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.status"], "rejected")
        self.assertEqual(attrs["arbiter.failure_category"], "match_not_running")

    async def test_tool_span_failure_on_exception(self) -> None:
        from app.agents.tools.base import BaseTool
        from app.agents.tools.models import ToolCost

        class ExplodingTool(BaseTool):
            def __init__(self) -> None:
                super().__init__(
                    name="explode",
                    description="boom",
                    allowed_agents=frozenset({AgentType.PRISONER}),
                    cost=ToolCost.BASH,
                )

            async def execute(self, context, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("kaboom")

        engine = self.make_engine()
        await engine.start()
        engine.registry.register(ExplodingTool())
        with self.assertRaises(RuntimeError):
            await engine.execute_tool_call(
                AgentType.PRISONER, ToolCall(name="explode", arguments={})
            )
        tools = self.spans.arbiter_spans("tool")
        self.assertEqual(len(tools), 1)
        attrs = self.spans.attrs(tools[0])
        self.assertEqual(attrs["arbiter.status"], "failed")
        self.assertFalse(attrs["arbiter.success"])
        self.assertEqual(attrs["arbiter.failure_category"], "execution_error")

    # -- output bounding -------------------------------------------------

    def test_output_telemetry_is_bounded(self) -> None:
        big = "x" * 5000
        tele = output_telemetry(big)
        self.assertEqual(tele["arbiter.output_size"], 5000)
        self.assertTrue(tele["arbiter.output_truncated"])
        self.assertEqual(len(tele["arbiter.output_preview"]), 2000)
        small = output_telemetry("ok")
        self.assertFalse(small["arbiter.output_truncated"])
        self.assertEqual(small["arbiter.output_preview"], "ok")

    # -- pydantic spans: agent runs + chats -------------------------------

    async def test_pydantic_spans_enriched_and_nested_in_match(self) -> None:
        agent: Agent[None, str] = Agent(_text_model(), output_type=str)
        with match_span(match_id="m-1", challenge_id="c-1"):
            with agent_observability_context(agent_role="prisoner"):
                first = await agent.run("hello")
            with agent_observability_context(agent_role="warden"):
                second = await agent.run("hello")
        self.assertEqual(first.output, "done")
        self.assertEqual(second.output, "done")

        agents = self.spans.arbiter_spans("agent")
        chats = self.spans.arbiter_spans("chat")
        matches = self.spans.arbiter_spans("match")
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(agents), 2)
        self.assertEqual(len(chats), 2)
        roles = sorted(
            self.spans.attrs(a)["arbiter.agent_role"] for a in agents
        )
        self.assertEqual(roles, ["prisoner", "warden"])
        for span in agents + chats:
            attrs = self.spans.attrs(span)
            self.assertEqual(attrs["arbiter.match_id"], "m-1")
            self.assertIn(attrs["arbiter.agent_role"], ("prisoner", "warden"))

        # Same trace, descendants of the match span.
        trace_ids = {s.context.trace_id for s in self.spans.spans()}
        self.assertEqual(len(trace_ids), 1)
        match_id = format(matches[0].context.span_id, "016x")
        by_id = {format(s.context.span_id, "016x"): s for s in self.spans.spans()}
        for span in agents + chats:
            ancestor = span
            seen_match = False
            while ancestor.parent is not None:
                ancestor = by_id[format(ancestor.parent.span_id, "016x")]
                if format(ancestor.context.span_id, "016x") == match_id:
                    seen_match = True
                    break
            self.assertTrue(seen_match, f"{span.name} not under match span")

        # Chat spans still carry Pydantic AI content (no manual duplication).
        for chat in chats:
            attrs = self.spans.attrs(chat)
            self.assertIn("gen_ai.input.messages", attrs)
            self.assertIn("gen_ai.output.messages", attrs)

    async def test_spans_outside_match_are_untouched(self) -> None:
        agent: Agent[None, str] = Agent(_text_model(), output_type=str)
        await agent.run("hello")
        for span in self.spans.spans():
            self.assertNotIn(
                "arbiter.match_id", dict(span.attributes or {})
            )


if __name__ == "__main__":
    unittest.main()
