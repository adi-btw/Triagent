"""The one thing the agent model is allowed to produce: an ``AgentDecision``.

Why a closed set of three actions instead of free-form tool calls: every action maps
to code we wrote and tested (retrieve again, stop and ask, write the report). The model
picks *which* transition to take; it cannot invent a new one, and it never touches k,
retrieval mode, budgets or the citation allow-list (see ``app.agent.workflow``).

The schema checks only what can be checked from the decision alone ("a rewrite must
carry a query"). Rules that need the run's history ("the query must differ from the
ones already tried", "no second clarifying question") are enforced by the workflow,
because only the workflow knows that history.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

AgentAction = Literal["draft_report", "rewrite_query", "ask_clarifying_question"]
ACTIONS: tuple[AgentAction, ...] = ("draft_report", "rewrite_query", "ask_clarifying_question")


class AgentDecision(BaseModel):
    """The model's choice for the next step, plus a short reason shown in the UI."""

    action: AgentAction
    rationale: str = Field(
        description="At most two sentences explaining the choice; shown to the user."
    )
    rewritten_query: str | None = Field(
        default=None,
        description="Required when action is rewrite_query: a new search query that "
        "differs from the queries already tried. Otherwise null.",
    )
    clarifying_question: str | None = Field(
        default=None,
        description="Required when action is ask_clarifying_question: one short question "
        "for the reporter. Otherwise null.",
    )

    @model_validator(mode="after")
    def _payload_matches_action(self) -> Self:
        """A rewrite needs a query and a question needs text; stray fields are dropped.

        Raising here makes the decision *malformed*, which the workflow turns into a
        recorded fallback to ``draft_report``. Clearing irrelevant fields (instead of
        rejecting them) is deliberate leniency: a model that fills both fields has still
        made an unambiguous choice via ``action``.
        """
        self.rewritten_query = (self.rewritten_query or "").strip() or None
        self.clarifying_question = (self.clarifying_question or "").strip() or None
        if self.action == "rewrite_query" and self.rewritten_query is None:
            raise ValueError("rewrite_query requires a non-empty rewritten_query")
        if self.action == "ask_clarifying_question" and self.clarifying_question is None:
            raise ValueError("ask_clarifying_question requires a non-empty clarifying_question")
        if self.action != "rewrite_query":
            self.rewritten_query = None
        if self.action != "ask_clarifying_question":
            self.clarifying_question = None
        return self
