from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Step(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    timer_seconds: int | None = Field(default=None, ge=1, le=86400)

class Workflow(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=100)
    mode: Literal["study", "cooking", "experiment"]
    approved_by: str = Field(min_length=1)
    pack: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    steps: list[Step] = Field(min_length=1, max_length=100)

class Command(StrictModel):
    action: Literal["start", "confirm", "pause", "resume", "stop", "quiet", "snooze"]
    workflow_id: str | None = None
    permission_confirmed: bool = False
    enabled: bool = True
    seconds: int = Field(default=300, ge=1, le=3600)

class PairRequest(StrictModel):
    code: str = Field(min_length=6, max_length=6)

class Entitlement(StrictModel):
    device_id: str
    pack: str
    expires_at: int
    signature: str
