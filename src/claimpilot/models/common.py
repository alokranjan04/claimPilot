"""Shared leaf models used across multiple domain contracts."""

from decimal import Decimal

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    """A file attached to a claim (FNOL photo, police report, etc.)."""

    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    url: str = Field(
        min_length=1,
        description="Storage URL or path — never embedded binary in the model.",
    )


class Party(BaseModel):
    """A person or entity involved in the claim."""

    name: str = Field(min_length=1)
    role: str = Field(
        min_length=1,
        description="E.g. 'claimant', 'witness', 'third_party', 'insured'.",
    )
    contact: str = ""


class Citation(BaseModel):
    """A pointer to a specific clause in a source document."""

    clause_id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    snippet: str = Field(min_length=1)


class LineItem(BaseModel):
    """One line in a settlement breakdown."""

    description: str = Field(min_length=1)
    amount: Decimal = Field(
        description="Positive for payments, negative for deductions (e.g. deductible).",
    )
