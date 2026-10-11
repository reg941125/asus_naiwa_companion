"""Host-owned workflow state. No model may advance an approved step."""
import time
from dataclasses import dataclass
from .models import Workflow, Command
from .storage import Store

@dataclass
class Timer:
    label: str
    remaining: float
    deadline: float | None

class Engine:
    def __init__(self, workflows: dict[str, Workflow], store: Store, speak, clock=time.monotonic):
        self.workflows, self.store, self.speak, self.clock = workflows, store, speak, clock
        self.workflow = None
        self.index = 0
        self.status = "idle"
        self.quiet = store.get("quiet", False)
        self.muted = False
        self.timers: list[Timer] = []
        self.next_reminder = 0.0
        self.absent_since = None

    def say(self, message):
        self.store.event(time.time(), "prompt", {"text": message})
        if not self.quiet and not self.muted:
            self.speak(message)

    def begin_step(self):
        step = self.workflow.steps[self.index]
        self.say(step.text)
        if step.timer_seconds:
            self.timers.append(Timer(f"{self.workflow.title}: step {self.index + 1}", step.timer_seconds, self.clock() + step.timer_seconds))

    def command(self, command: Command, packs: set[str]):
        action = command.action
        if action == "start":
            workflow = self.workflows.get(command.workflow_id)
            if workflow is None:
                raise ValueError("Unknown approved workflow")
            if workflow.pack and workflow.pack not in packs:
                raise PermissionError("This workflow requires an offline entitlement")
            if workflow.mode in {"cooking", "experiment"} and not command.permission_confirmed:
                raise ValueError("Confirm a permitted kitchen or approved supervised workspace")
            if self.status in {"running", "paused"}:
                raise ValueError("Stop the current session before switching workflows")
            self.workflow, self.index, self.status = workflow, 0, "running"
            self.timers.clear()
            self.absent_since = None
            self.next_reminder = 0.0
            self.begin_step()
        elif action == "confirm":
            if self.status != "running":
                raise ValueError("No running step to confirm")
            self.index += 1
            if self.index == len(self.workflow.steps):
                self.status = "completed"
                self.say(f"Completed {self.workflow.title}. {self.index} steps confirmed.")
            else:
                self.begin_step()
        elif action == "pause":
            if self.status != "running":
                raise ValueError("No running session")
            self.status = "paused"
            for timer in self.timers:
                if timer.deadline is not None:
                    timer.remaining = max(0, timer.deadline - self.clock())
                    timer.deadline = None
        elif action == "resume":
            if self.status != "paused":
                raise ValueError("No paused session")
            self.status = "running"
            for timer in self.timers:
                timer.deadline = self.clock() + timer.remaining
        elif action == "stop":
            if self.workflow:
                self.say(f"Session ended. {self.index} steps confirmed in {self.workflow.title}.")
            self.status = "idle"
            self.workflow = None
            self.timers.clear()
        elif action == "quiet":
            self.quiet = command.enabled
            self.store.set("quiet", self.quiet)
        elif action == "snooze":
            self.next_reminder = self.clock() + command.seconds
        self.store.event(time.time(), "command", {"action": action})

    def tick(self):
        now = self.clock()
        for timer in list(self.timers):
            if timer.deadline is not None and now >= timer.deadline:
                self.timers.remove(timer)
                self.say(f"Timer finished: {timer.label}. Confirm when you are ready.")
        if (self.status == "running" and self.workflow.mode == "study" and
                self.absent_since is not None and now - self.absent_since >= 60 and now >= self.next_reminder):
            self.say("You have been away from the desk. Would you like to pause or continue?")
            self.next_reminder = now + 300

    def presence(self, present: bool | None):
        # Unknown perception is never treated as evidence of absence.
        if present is not False:
            self.absent_since = None
        elif present is False and self.absent_since is None:
            self.absent_since = self.clock()
