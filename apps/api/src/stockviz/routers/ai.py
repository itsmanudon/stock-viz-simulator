"""`/v1/ai` (A8.2, A8.3): what the server's model may draft.

- `GET /v1/ai/status` (public): whether a provider is set up, and which.
- `POST /v1/ai/rule` (signed in, 10 a minute): plain English to Rule DSL.
  The draft is checked by the same code as `/v1/rules/check`; nothing runs.
  409 when no provider is set up; 502 when the provider fails.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from stockviz.auth import UserIdDep
from stockviz.limiter import limiter
from stockviz.schemas import AiRuleAttemptOut, AiRuleIn, AiRuleOut, AiStatusOut
from stockviz.services.ai import rules as ai_rules
from stockviz.services.ai.provider import AiNotConfigured, AiProviderError, provider_from_settings
from stockviz.settings import get_settings

router = APIRouter(prefix="/v1/ai", tags=["ai"])

NOTE = (
    "Drafted by a model and checked by the rule checker. Read it before you use it: the "
    "checker proves it is a valid rule, not that it is the rule you meant."
)


@router.get("/status", response_model=AiStatusOut)
def ai_status() -> AiStatusOut:
    try:
        provider = provider_from_settings(get_settings())
    except AiNotConfigured as exc:
        return AiStatusOut(configured=False, reason=str(exc))
    return AiStatusOut(configured=True, provider=provider.name, model=provider.model)


@router.post("/rule", response_model=AiRuleOut)
@limiter.limit("10/minute")
def ai_rule(request: Request, body: AiRuleIn, user_id: UserIdDep) -> AiRuleOut:
    del request, user_id
    try:
        provider = provider_from_settings(get_settings())
        out = ai_rules.translate(provider, body.text, timeframe=body.timeframe)
    except AiNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except AiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return AiRuleOut(
        request=out.request,
        provider=out.provider,
        model=out.model,
        rule=out.rule,
        check=out.check,
        attempts=[AiRuleAttemptOut(rule=a.rule, check=a.check) for a in out.attempts],
        note=NOTE,
    )
