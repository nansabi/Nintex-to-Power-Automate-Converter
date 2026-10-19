"""Power Automate connector, action, and schema constants.

All constants are centralized here to maintain a clean single source of truth.
Each section maps to official Power Automate flow definitions.
Always verify action schemas and parameter names against official Microsoft documentation.
"""

from __future__ import annotations

# =============================================================================
# Trigger Definitions
# Verify against Microsoft docs: Power Automate Request trigger schema
# =============================================================================
TRIGGER_TYPE_REQUEST = "Request"
TRIGGER_KIND_BUTTON = "Button"
TRIGGER_NAME_MANUAL = "manual"

# =============================================================================
# Action Types and Common Enums
# Verify against Microsoft docs: Power Automate action types & runAfter
# =============================================================================
ACTION_TYPE_OPEN_API_CONNECTION = "OpenApiConnection"
ACTION_TYPE_IF = "If"
ACTION_TYPE_INITIALIZE_VARIABLE = "InitializeVariable"
ACTION_TYPE_SET_VARIABLE = "SetVariable"
RUN_AFTER_STATUS_SUCCEEDED = "Succeeded"
DEFAULT_VARIABLE_TYPE = "String"

# =============================================================================
# Office 365 Outlook Connector Constants
# Verify against Microsoft docs: Send an email (V2) action schema
# =============================================================================
O365_CONNECTION_NAME = "shared_office365"
O365_OPERATION_ID_SEND_EMAIL_V2 = "SendEmailNotification_V2"
O365_API_ID = "/providers/Microsoft.PowerApps/apis/shared_office365"
O365_PARAM_TO = "emailMessage/To"
O365_PARAM_SUBJECT = "emailMessage/Subject"
O365_PARAM_BODY = "emailMessage/Body"

# =============================================================================
# Approvals Connector Constants
# Verify against Microsoft docs: Start and wait for an approval action schema
# =============================================================================
APPROVALS_CONNECTION_NAME = "shared_approvals"
APPROVALS_OPERATION_ID_START_AND_WAIT = "StartAndWaitForAnApproval"
APPROVALS_API_ID = "/providers/Microsoft.PowerApps/apis/shared_approvals"
APPROVALS_TYPE_FIRST_TO_RESPOND = "ApproveRejectFirstToRespond"
APPROVALS_PARAM_TITLE = "title"
APPROVALS_PARAM_ASSIGNED_TO = "assignedTo"
APPROVALS_PARAM_TYPE = "approvalType"

# =============================================================================
# Approval Outcome Mapping
# Verify against Microsoft docs: Approvals outcome values in condition expressions
# =============================================================================
OUTCOME_APPROVE = "Approve"
OUTCOME_REJECT = "Reject"
