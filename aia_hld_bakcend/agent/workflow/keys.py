"""
Single source of truth for session state keys used across:
- Workflow agents (SequentialAgent / LoopAgent gates)
- Prompts (state templating placeholders)
- StateStore derivations
- Output/Presenter agent display
"""

# ---------------------------------------------------------------------
# Intake (derived by StateStore)
# ---------------------------------------------------------------------
KEY_INTAKE = "intake"
KEY_INTAKE_CONFIRMED = "intake_confirmed"
KEY_INTAKE_COMPLETE = "intake_complete"
KEY_INTAKE_MISSING_FIELDS = "intake_missing_fields"
KEY_INTAKE_VALIDATION_ERROR = "intake_validation_error"

# Original high-level user ask for context
KEY_USER_REQUEST = "user_request"


# ---------------------------------------------------------------------
# Blueprint outputs
# ---------------------------------------------------------------------
KEY_BLUEPRINT_RESULTS = "blueprint_results"
KEY_BLUEPRINT_SELECTED = "blueprint_selected"
KEY_BLUEPRINT_SEARCH_DONE = "blueprint_search_done"
KEY_BLUEPRINT_NO_MATCH = "blueprint_no_match"


# ---------------------------------------------------------------------
# Research outputs
# ---------------------------------------------------------------------
KEY_RESEARCH_RESOLVED = "research_resolved"
KEY_TECHNICAL_RESEARCH_SUMMARY = "technical_research_summary"

# Fallback/Additional research keys
KEY_RESEARCH_OUTPUT = "research_output"
KEY_RESEARCH_REPORT_JSON = "research_report_json"
KEY_RESEARCH_SUMMARY = "research_summary"
KEY_RESOLVED_SERVICES = "resolved_services"

# Research retry state
KEY_RESEARCH_RETRY_COUNT = "research_retry_count"
KEY_RESEARCH_RETRY_MAX = "research_retry_max"
KEY_RESEARCH_RETRY_REASON = "research_retry_reason"


# ---------------------------------------------------------------------
# Architecture outputs
# ---------------------------------------------------------------------
KEY_ARCH_COMPLETE = "architecture_complete"
KEY_HLD_REPORT_JSON = "hld_report_json"

# Magic flag for the Orchestrator's greedy JSON extractor
KEY_HLD_COMMIT_TRIGGERED = "hld_commit_triggered"

# Architecture Validation Loop (Root/Orchestrator control)
KEY_ARCH_VALID = "architecture_valid"
KEY_VALIDATION_ERROR = "validation_error"
KEY_HLD_VALIDATION_ERROR = "hld_validation_error"
KEY_VALIDATION_FEEDBACK = "validation_feedback"


# ---------------------------------------------------------------------
# Rendering outputs
# ---------------------------------------------------------------------
KEY_DOC_RENDERED = "document_rendered"
KEY_DOC_RENDER_STARTED = "doc_render_started"

# Paths to generated files
KEY_RENDER_ARTIFACT = "rendered_doc_path"
KEY_RENDERED_PDF_PATH = "rendered_pdf_path"

# Local browser/download URLs
KEY_LOCAL_DOWNLOAD_URLS = "local_download_urls"
KEY_LOCAL_VIEW_URLS = "local_view_urls"

# Diagnostic keys
KEY_DOC_RENDER_WARNING = "doc_render_warning"
KEY_DOC_RENDER_ERROR = "doc_render_error"


# ---------------------------------------------------------------------
# Workflow Meta-State
# ---------------------------------------------------------------------
KEY_ACTIVE_AGENT = "active_agent"
KEY_WORKFLOW_COMPLETE = "workflow_complete"
KEY_INITIALIZED = "_initialized"


# ---------------------------------------------------------------------
# Revision / Reset flow
# ---------------------------------------------------------------------
KEY_WORKFLOW_RESET_REQUESTED = "workflow_reset_requested"
KEY_REVISION_REQUESTED = "revision_requested"
KEY_REVISION_NOTES = "revision_notes"
KEY_REVISION_CONTEXT = "revision_context"

# Backward compatibility / legacy alias-style key
KEY_REVISION_REQUEST = "revision_request"

KEY_REVISION_READY = "revision_ready"
KEY_ORIGINAL_USER_REQUEST = "original_user_request"


# ---------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------
KEY_SELECTED_SECTIONS = "selected_sections"


# ---------------------------------------------------------------------
# Section-wise HLD state / retry state
# ---------------------------------------------------------------------
KEY_HLD_SECTION_STATE_PREFIX = "hld_"

KEY_SECTION_RETRY_TARGET = "section_retry_target"
KEY_SECTION_RETRY_QUEUE = "section_retry_queue"
KEY_SECTION_RETRY_COUNTS = "section_retry_counts"
KEY_SECTION_RETRY_MODE = "section_retry_mode"
KEY_RENDER_SELECTED_SECTIONS = "render_selected_sections"