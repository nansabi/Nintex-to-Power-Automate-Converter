"""FastAPI application providing REST and webhook endpoints for workflow conversion.

Exposes endpoints for health checking, workflow conversion, and incoming
webhook integration with HMAC-SHA256 signature verification.
"""

from __future__ import annotations

import hmac
import hashlib
import os
from typing import Any
from pydantic import BaseModel, Field
from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from src.service import convert_workflow_xml

app = FastAPI(
    title="Nintex to Power Automate Conversion API",
    description="REST API for parsing and converting legacy Nintex workflows to Power Automate flows.",
    version="1.0.0",
)


class ConvertRequest(BaseModel):
    """Payload for direct workflow conversion request."""

    workflow_xml: str = Field(..., description="Raw Nintex workflow XML string")
    use_llm: bool = Field(
        default=False,
        description="Whether to query LLM for suggestions on unsupported actions (default: false)",
    )


class WebhookPayload(BaseModel):
    """Payload expected on webhook export notification."""

    event: str = Field(..., description="Event name, e.g. 'workflow.exported'")
    workflow_xml: str = Field(..., description="Exported Nintex workflow XML string")


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check() -> dict[str, str]:
    """Health check endpoint to verify service availability.

    Returns:
        JSON status object indicating service health.
    """
    return {"status": "ok"}


@app.post("/convert", status_code=status.HTTP_200_OK)
def convert_endpoint(request: ConvertRequest) -> dict[str, Any]:
    """Convert a Nintex workflow XML payload into a Power Automate flow definition.

    Args:
        request: ConvertRequest containing XML text and optional use_llm flag.

    Returns:
        The resulting Power Automate flow JSON dictionary and conversion report.
    """
    result = convert_workflow_xml(request.workflow_xml, use_llm=request.use_llm)
    if not result.get("success", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Conversion failed"),
        )
    return result


@app.post("/webhook/workflow-exported", status_code=status.HTTP_200_OK)
async def webhook_endpoint(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> dict[str, Any]:
    """Receive exported workflow events with mandatory HMAC-SHA256 verification.

    Requires:
      - WEBHOOK_SECRET environment variable configured on server (otherwise returns 503)
      - X-Signature header matching HMAC-SHA256(raw_request_body, WEBHOOK_SECRET)

    Args:
        request: Raw FastAPI Request to obtain exact bytes for HMAC calculation.
        x_signature: Header containing hex-encoded HMAC-SHA256 signature.

    Returns:
        Converted flow result on successful verification.
    """
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured on this server.",
        )

    if not x_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-Signature header.",
        )

    raw_body = await request.body()

    # Compute expected HMAC-SHA256 signature
    computed_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, x_signature.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature.",
        )

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload in webhook body.",
        )

    xml_text = data.get("workflow_xml")
    if not xml_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'workflow_xml' in webhook payload.",
        )

    result = convert_workflow_xml(xml_text, use_llm=False)
    if not result.get("success", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Conversion failed"),
        )

    return result
