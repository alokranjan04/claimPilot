"""Models representing inbound claim data."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from claimpilot.models.common import Attachment, Party


class RawClaim(BaseModel):
    """The raw FNOL payload as received from the client."""

    claim_id: str = Field(min_length=1)
    policy_number: str = Field(min_length=1)
    fnol_text: str = Field(min_length=1)
    attachments: list[Attachment] = []


class ClaimFacts(BaseModel):
    """Structured facts extracted from the raw claim by the Intake agent."""

    incident_type: str = Field(min_length=1)
    incident_date: date
    claimed_amount: Decimal = Field(ge=Decimal(0))
    location: str = Field(min_length=1)
    parties: list[Party] = Field(min_length=1)
    extracted_fields: dict[str, str] = {}
