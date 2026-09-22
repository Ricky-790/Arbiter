from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict


class MatchSpanAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_type: str = "match"
    match_id: str
    challenge_id: str
    status: str = "running"
    winner: str | None = None
    end_reason: str | None = None

    def to_attributes(self) -> dict[str, Any]:
        return {
            f"arbiter.{key}": value
            for key, value in self.model_dump(exclude_none=True).items()
        }


class ToolSpanAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_type: str = "tool"
    match_id: str
    agent_role: str
    tool_name: str
    tool_args: dict={}
    status: str = "requested"

    success: bool | None = None
    exit_code: int | None = None
    credits_charged: int | None = None
    failure_category: str | None = None

    output_size: int | None = None
    output_truncated: bool | None = None
    output_preview: str | None = None

    def to_attributes(self) -> dict[str, Any]:
        return {
            f"arbiter.{key}": value
            for key, value in self.model_dump(exclude_none=True).items()
        }

class ToolResultAttributes(BaseModel):
    status: str
    success: bool | None = None
    exit_code: int | None = None
    credits_charged: int | None = None
    failure_category: str | None = None
    output_size: int | None = None
    output_truncated: bool | None = None
    output_preview: str | None = None
