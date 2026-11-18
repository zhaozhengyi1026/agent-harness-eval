"""Core data types shared by the runtime, tools and policy."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Task:
    """The part of a task the agent is allowed to see."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str

    @classmethod
    def from_public(cls, row: Dict[str, Any]) -> "Task":
        missing = {"instance_id", "repo", "base_commit", "problem_statement"} - row.keys()
        if missing:
            raise ValueError("Public task is missing fields: {}".format(sorted(missing)))
        return cls(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
        )


@dataclass(frozen=True)
class Action:
    """One tool call proposed by the model."""

    tool: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Outcome of an executed action."""

    ok: bool
    output: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    """One logged step of the session."""

    step: int
    tool: str
    args: Dict[str, Any]
    decision: str
    reason: str
    ok: bool
    output: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "args": self.args,
            "decision": self.decision,
            "reason": self.reason,
            "ok": self.ok,
            "output": self.output,
        }
