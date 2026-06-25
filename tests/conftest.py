"""Shared fixtures for ClaimPilot tests."""

from __future__ import annotations

import pytest

from claimpilot.rag.models import SourceDoc


@pytest.fixture()
def synthetic_corpus() -> list[SourceDoc]:
    """Small bundled synthetic policy corpus for RAG tests.

    Three documents with distinct section structures, clause IDs that
    are easy to target with BM25, and enough text to exercise chunking.
    """
    return [
        SourceDoc(
            doc_id="POL-100",
            title="Standard Auto Policy",
            text=(
                "# §1.1 Comprehensive Coverage\n"
                "This section covers damage to the insured vehicle from collisions, "
                "theft, vandalism, weather events, and animal strikes. The deductible "
                "is $500 per incident. Maximum payout is the actual cash value (ACV) "
                "of the vehicle at the time of loss.\n\n"
                "# §1.2 Liability Coverage\n"
                "Covers bodily injury and property damage the insured causes to "
                "others. Minimum limits: $25,000 per person / $50,000 per accident "
                "for bodily injury and $25,000 for property damage.\n\n"
                "# §1.3 Exclusions\n"
                "This policy does not cover intentional damage, racing, commercial "
                "use of a personal vehicle, or wear and tear. Flood damage requires "
                "a separate endorsement.\n\n"
                "# §1.4 Claims Procedure\n"
                "The insured must file a claim within 30 days of the incident. "
                "Documentation required: police report (if applicable), photographs "
                "of damage, and a repair estimate from a licensed shop."
            ),
            metadata={"jurisdiction": "IL", "policy_type": "auto"},
        ),
        SourceDoc(
            doc_id="POL-200",
            title="Homeowners Policy HO-3",
            text=(
                "# §2.1 Dwelling Coverage\n"
                "Covers the structure of the home against fire, windstorm, hail, "
                "lightning, and explosion. Replacement cost basis up to the policy "
                "limit. Deductible: 1% of dwelling coverage amount.\n\n"
                "# §2.2 Personal Property\n"
                "Covers personal belongings (furniture, electronics, clothing) up "
                "to 50% of dwelling coverage. Special limits apply to jewelry "
                "($1,500), firearms ($2,500), and collectibles ($500).\n\n"
                "# §2.3 Flood Exclusion\n"
                "Flood damage is explicitly excluded from this policy. The insured "
                "must purchase a separate NFIP flood policy for flood coverage."
            ),
            metadata={"jurisdiction": "IL", "policy_type": "homeowners"},
        ),
        SourceDoc(
            doc_id="REG-001",
            title="Illinois Insurance Regulation 2024",
            text=(
                "# §R.1 Timely Processing\n"
                "All claims must be acknowledged within 15 business days of "
                "receipt. The insurer must issue a decision within 45 calendar "
                "days unless additional investigation is documented.\n\n"
                "# §R.2 Fair Settlement Practices\n"
                "Insurers must offer settlements based on the actual cash value "
                "or replacement cost as defined in the policy. Low-ball offers "
                "that do not reflect market value are a violation.\n\n"
                "# §R.3 Anti-Fraud Requirements\n"
                "Insurers must maintain a special investigations unit (SIU) and "
                "report suspected fraud to the Illinois Department of Insurance "
                "within 60 days of detection."
            ),
            metadata={"jurisdiction": "IL", "policy_type": "regulation"},
        ),
    ]
