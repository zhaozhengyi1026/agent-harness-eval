"""The hand-written loop: propose action, enforce policy, execute, log."""

import json
from pathlib import Path
from typing import List

from .policy import ASK, DENY, Policy
from .schemas import Action, Event, Task
from .tools import ToolBox


class ScriptedModel:
    """Deterministic stand-in for a model, used before any real model is wired."""

    def __init__(self, actions: List[Action]):
        self._actions = list(actions)

    def next_action(self, task: Task, history: List[Event]) -> Action:
        if not self._actions:
            return Action("finish", {})
        return self._actions.pop(0)


class Runtime:
    def __init__(self, model, toolbox: ToolBox, policy: Policy, log_path: Path,
                 max_steps: int = 20):
        self.model = model
        self.toolbox = toolbox
        self.policy = policy
        self.log_path = Path(log_path)
        self.max_steps = max_steps

    def _log(self, event: Event) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.as_dict(), ensure_ascii=False) + "\n")

    def run(self, task: Task) -> dict:
        history: List[Event] = []
        status = "budget_exceeded"
        for step in range(1, self.max_steps + 1):
            action = self.model.next_action(task, history)
            decision, reason = self.policy.check(action)
            if decision == DENY:
                event = Event(step, action.tool, dict(action.args), decision, reason,
                              False, "not executed")
                history.append(event)
                self._log(event)
                continue
            if decision == ASK:
                event = Event(step, action.tool, dict(action.args), decision, reason,
                              False, "approval required; scripted run has no approver")
                history.append(event)
                self._log(event)
                continue
            result = self.toolbox.execute(action)
            event = Event(step, action.tool, dict(action.args), decision, reason,
                          result.ok, result.output)
            history.append(event)
            self._log(event)
            if action.tool == "finish":
                status = "finished"
                break
        return {
            "status": status,
            "steps": len(history),
            "denied": sum(1 for e in history if e.decision == DENY),
            "asked": sum(1 for e in history if e.decision == ASK),
            "tool_errors": sum(1 for e in history if e.decision == "allow" and not e.ok),
            "events": [event.as_dict() for event in history],
        }
