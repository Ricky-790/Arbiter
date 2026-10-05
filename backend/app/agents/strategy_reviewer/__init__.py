"""The Strategy Reviewer: reads a finished match, proposes a better strategy."""

from .prompt import ReviewRequest, build_review_prompt
from .reviewer import StrategyReviewerAgent

__all__ = [
    "ReviewRequest",
    "StrategyReviewerAgent",
    "build_review_prompt",
]
