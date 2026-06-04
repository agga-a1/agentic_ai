"""
aia_intake_schema.py

Canonical intake schema used by the AIA workflow.
This schema is the single source of truth for determining intake completeness.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, AliasChoices, ConfigDict


class IntakeSchema(BaseModel):
    """
    Canonical intake contract. Backend uses this schema to determine intake completeness.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    project_name: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("project_name", "Project Name"),
    )

    project_code: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("project_code", "Project Code"),
    )

    business_objective: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "business_objective",
            "Business Objective",
            "objective",
        ),
    )

    source_system: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("source_system", "Source System"),
    )

    target_system: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("target_system", "Target System"),
    )

    data_residency: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "data_residency",
            "Data Residency",
            "data_residency_region",
        ),
        description='Data residency requirement (e.g. UK, EU, India, Global, TBC)',
    )

    encryption_requirements: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "encryption_requirements",
            "Encryption Requirements",
        ),
        description="Encryption requirement or expectation for the solution",
    )

    deployment_strategy: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("deployment_strategy", "Deployment Strategy"),
    )

    execution_model: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("execution_model", "Execution Model"),
    )

    data_movement_type: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("data_movement_type", "Data Movement Type"),
    )

    ci_cd_preference: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "ci_cd_preference",
            "cicd_preference",
            "CI/CD Preference",
        ),
        description="CI/CD tool or preference (e.g. Cloud Build, Jenkins, GitHub Actions)",
    )

    pii_status: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("pii_status", "PII Status"),
    )

    cmek_status: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("cmek_status", "CMEK Status"),
        description="Whether CMEK is required / enabled / applicable",
    )

    additional_context: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "additional_context",
            "Additional Context",
            "others",
            "others_additional_context",
        ),
    )