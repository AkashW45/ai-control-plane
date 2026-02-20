from pydantic import BaseModel

class ExecutionPlan(BaseModel):
    risk: str
    runbook: str
    environment: str
    approval_required: bool
    confidence: float
