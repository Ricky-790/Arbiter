"""What the reviewer is asked to improve, and the user prompt that says so.

The prompt carries the challenge's own framing -- description, win condition,
and the target side's hint -- plus the strategy being improved and the tools
that side actually has, so the proposal is grounded in the game rather than in
what the model assumes the sandbox is like.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.models import AgentType


@dataclass(frozen=True)
class ReviewRequest:
    """The side being improved, and the challenge it is being improved for."""

    side: str
    #: The saved strategy to beat. Empty when the side ran without one.
    strategy: str
    challenge_name: str
    challenge_description: str
    win_condition: str
    #: That side's own challenge hint. Only ever its own: the hints are how the
    #: challenge keeps what each role starts out knowing asymmetric, and the
    #: reviewer's output is handed straight to that side, so putting the
    #: opponent's hint in this prompt would leak it into the side's briefing.
    hint: str | None = None


def tools_for(side: str) -> list[str]:
    """The tool names the given side may use, in registration order."""
    from app.agents.tools.registry import build_default_registry

    registry = build_default_registry()
    return [tool.name for tool in registry.get_for_agent(AgentType(side))]


def build_review_prompt(request: ReviewRequest) -> str:
    """The user prompt for one review run.

    Only ever the ``user`` role's hint appears, and the opponent is described
    but not briefed: the reviewer needs to know a match has two sides and what
    each was trying to do, not what the other one was secretly told.
    """
    tools = ", ".join(tools_for(request.side))
    lines = [
        (
            "Review the match under review and write a better strategy for the "
            f"{request.side}."
        ),
        "",
        f"Challenge: {request.challenge_name}",
        f"Description: {request.challenge_description}",
        f"Win condition: {request.win_condition}",
    ]
    if request.hint and request.hint.strip():
        lines.append(f"What the {request.side} is told up front: {request.hint.strip()}")
    lines += [
        "",
        f"The {request.side}'s strategy in the match you are reviewing was:",
        request.strategy.strip() or "(none was given)",
        "",
        f"The tools available to the {request.side} are: {tools}.",
        "",
        (
            "Use your tools to find out what actually happened in that match, "
            f"then reply with the improved strategy for the {request.side}."
        ),
    ]
    return "\n".join(lines)
