from __future__ import annotations

from app.domain.models import FederatedRiskSignal
from pydantic import BaseModel, Field


class FederatedNodeUpdate(BaseModel):
    node_id: str
    institution_type: str
    local_sample_count: int
    clipped_update: list[float]
    local_risk_indicators: list[str] = Field(default_factory=list)

