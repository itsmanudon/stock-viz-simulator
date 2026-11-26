"""`POST /v1/rules/check` (A2.2): validate a Rule DSL rule.

Public and rate-limited like the other public reads (60/min). The web rule
editor calls it from the browser as the user types (debounced). Always 200:
``valid`` with the canonical text, hash, type and warm-up, or ``error`` with
its kind, message, line and column.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from stockviz.limiter import limiter
from stockviz.schemas import RuleCheckIn, RuleCheckOut
from stockviz.services.setups.rules import check_rule

router = APIRouter(prefix="/v1/rules", tags=["rules"])


@router.post("/check", response_model=RuleCheckOut)
@limiter.limit("60/minute")
def check(request: Request, body: RuleCheckIn) -> RuleCheckOut:
    return check_rule(body.rule, body.expect)
