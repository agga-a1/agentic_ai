
from pydantic import BaseModel, ConfigDict, AliasGenerator, Field
from typing import Dict, List, Any, Optional

# ============================================================
# THE FOUNDATION
# ============================================================
class AIA_BaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=lambda s: s.replace("_", "").replace("document", "").replace("key", "").lower(),
        ),
        populate_by_name=True,
        extra='allow'
    )

# ============================================================
# METADATA & CONTROL BLOCKS
# ============================================================
class DocumentMetadata(AIA_BaseModel):
    template_name: str = "Universal HLD"
    template_version: str = "1.0"
    classification: str = "Internal"
    domain: str = "Cross-Domain"
    source_file: str = "AIA_Generated"

class DeploymentContext(AIA_BaseModel):
    primary_region: str = "TBC"
    secondary_region: str = "TBC"
    region_rationale: str = "TBC"

class ProjectDetails(AIA_BaseModel):
    project_name: str = "TBC"
    project_code: str = "TBC"
    version: str = "0.1"
    status: str = "Draft"
    published_date: str = "TBC"
    team: str = "TBC"
    author: str = "TBC"
    # ---> TAG ADDED HERE <---
    deployment_context: Optional[DeploymentContext] = Field(
        default_factory=DeploymentContext,
        json_schema_extra={"is_metadata": True}
    )

class HistoryRecord(AIA_BaseModel):
    status: str = "TBC"
    version: str = "TBC"
    date: str = "TBC"
    author: str = "TBC"
    change_summary: str = "TBC"

class Reviewer(AIA_BaseModel):
    name: str = "TBC"
    email: str = "TBC"
    team: str = "TBC"
    role: str = "TBC"
    reviewed_version: str = "TBC"

class Approver(AIA_BaseModel):
    name: str = "TBC"
    email: str = "TBC"
    team: str = "TBC"
    role: str = "TBC"
    date: str = "TBC"
    version: str = "TBC"
    approval_email: str = "TBC"

class DocumentControl(AIA_BaseModel):
    history: List[HistoryRecord] = Field(default_factory=list)
    key_reviewers: List[Reviewer] = Field(default_factory=list)
    key_approvers: List[Approver] = Field(default_factory=list)

# ============================================================
# RAID SECTION
# ============================================================
class RaidSection(AIA_BaseModel):
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)

# ============================================================
# ARCHITECTURE DESIGN BLOCKS
# ============================================================
class ViewSection(AIA_BaseModel):
    diagrams: List[str] = Field(default_factory=list)

class DesignViewsSection(AIA_BaseModel):
    logical_view: ViewSection = Field(default_factory=ViewSection)
    physical_view: ViewSection = Field(default_factory=ViewSection)
    process_view: ViewSection = Field(default_factory=ViewSection)    

# ============================================================
# DATA DESIGN BLOCKS
# ============================================================
class DataDesignSection(AIA_BaseModel):
    data_flow: ViewSection = Field(default_factory=ViewSection) 
    impact_summary: List[Dict[str, Any]] = Field(default_factory=list)
    logical_data_model: List[Dict[str, Any]] = Field(default_factory=list)
    data_storage: List[Dict[str, Any]] = Field(default_factory=list)
    subject_areas: List[Dict[str, Any]] = Field(default_factory=list)

# ============================================================
# INTEGRATION, SECURITY, & COMPLIANCE BLOCKS
# ============================================================
class Interfaces(AIA_BaseModel):
    internal_interfaces: List[Dict[str, Any]] = Field(default_factory=list)
    external_interfaces: List[Dict[str, Any]] = Field(default_factory=list)
    machine_to_machine: List[Dict[str, Any]] = Field(default_factory=list)
    person_to_machine: List[Dict[str, Any]] = Field(default_factory=list)

class SecuritySection(AIA_BaseModel):
    security_zones: List[Dict[str, Any]] = Field(default_factory=list)
    access_control: List[Dict[str, Any]] = Field(default_factory=list)
    auditing_logging: List[Dict[str, Any]] = Field(default_factory=list)
    encryption: List[Dict[str, Any]] = Field(default_factory=list)

class CostItem(AIA_BaseModel):
    service_name: str = "TBC"
    cost_driver: str = "TBC"
    pricing_model: str = "TBC"
    assumptions: str = "TBC"
    estimated_monthly_cost_gbp: str = "TBC"

class SolutionCheckSection(AIA_BaseModel):
    compliance_checks: List[Dict[str, Any]] = Field(default_factory=list)
    operational_performance: List[Dict[str, Any]] = Field(default_factory=list)
    cost_considerations: List[CostItem] = Field(default_factory=list)

# ============================================================
# MAIN HLD SCHEMA
# ============================================================
class HLDReport(AIA_BaseModel):
    """
    Universal HLD Schema.
    Combines application, infrastructure, and data warehouse patterns.
    """
    # ---> TAGS ADDED HERE <---
    document_metadata: DocumentMetadata = Field(
        title="Document Metadata", 
        default_factory=DocumentMetadata,
        json_schema_extra={"is_metadata": True}
    )
    project_details: ProjectDetails = Field(
        title="Project Details", 
        default_factory=ProjectDetails,
        json_schema_extra={"is_metadata": True}
    )
# Tagging Document Control as metadata for horizontal rendering
    document_control: DocumentControl = Field(
        title="Document Control", 
        default_factory=DocumentControl,
        json_schema_extra={"is_metadata": True} # <-- ADDED
    )
    executive_summary: Any = Field(title="Executive Summary", default_factory=dict)
    summary_of_functionality: Any = Field(title="Summary Of Functionality", default_factory=dict)
    
    supporting_artefacts: List[Dict[str, Any]] = Field(title="Supporting Artefacts", default_factory=list)
    raid: RaidSection = Field(title="RAID (Risks, Assumptions, Issues, Dependencies)", default_factory=RaidSection)
    design_decisions: List[Dict[str, Any]] = Field(title="Design Decisions", default_factory=list)
    
    design_views: DesignViewsSection = Field(title="Architecture Design Views", default_factory=DesignViewsSection)
    data_design: DataDesignSection = Field(title="Data Design & Models", default_factory=DataDesignSection)
    entity_summary: List[Dict[str, Any]] = Field(title="Component / Entity Summary", default_factory=list)
    interfaces: Interfaces = Field(title="System Interfaces", default_factory=Interfaces)
    
    security: SecuritySection = Field(title="Security Architecture", default_factory=SecuritySection)
    solution_check: SolutionCheckSection = Field(title="Solution Checks & NFRs", default_factory=SolutionCheckSection)
    
    glossary: List[Dict[str, Any]] = Field(title="Glossary", default_factory=list)