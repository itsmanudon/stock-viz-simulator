"""`/v1/ai` (A8.2, A8.3): what the server's model may draft.

- `GET /v1/ai/status` (public): whether a provider is set up, and which.
- `POST /v1/ai/rule` (signed in, 10 a minute): plain English to Rule DSL.
  The draft is checked by the same code as `/v1/rules/check`; nothing runs.
  409 when no provider is set up; 502 when the provider fails.
- `POST /v1/ai/ask` (signed in, 10 a minute; A8.5, M11.2): a question about
  stored documents, answered from A8.4's passages with citations checked.
  409 without a provider, 502 when it fails, 404 an unknown ticker.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.routers.documents import _instrument, _kind, _naive, _out, _tickers
from stockviz.schemas import (
    AiRuleAttemptOut,
    AiRuleIn,
    AiRuleOut,
    AiStatusOut,
    AskIn,
    AskOut,
    AskSourceOut,
    PassageOut,
)
from stockviz.services.ai import copilot
from stockviz.services.ai import rules as ai_rules
from stockviz.services.ai.embed import embedder_from_settings
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


ASK_DISCLAIMER = (
    "Written by a model from the passages listed, which are the only sources it saw. "
    "Check every figure against its source. Not investment advice."
)


@router.post("/ask", response_model=AskOut)
@limiter.limit("10/minute")
def ai_ask(
    request: Request,
    body: AskIn,
    user_id: UserIdDep,
    session: Annotated[Session, Depends(get_session)],
) -> AskOut:
    del request, user_id
    iid = _instrument(session, body.ticker)[1] if body.ticker else None
    when = _naive(body.as_of)
    settings = get_settings()
    try:
        provider = provider_from_settings(settings)
    except AiNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        out = copilot.ask(
            session, provider, body.question, as_of=when, ticker_names=lambda ids: _tickers(session, ids),
            instrument_id=iid, kind=_kind(body.kind), embedder=embedder_from_settings(settings),
        )  # fmt: skip
    except AiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    names = _tickers(session, {p.document.instrument_id for p in out.sources})
    check = out.check
    cited = set(check.cited) if check else set()
    return AskOut(
        question=out.question,
        as_of=when,
        retrieval_mode=out.retrieval.mode,
        answer=out.answer or copilot.NOT_FOUND,
        grounded=bool(check and check.grounded),
        cited=sorted(cited),
        invalid_citations=check.invalid if check else [],
        uncited_sentences=check.uncited_sentences if check else 0,
        sources=[
            AskSourceOut(
                n=i,
                cited=i in cited,
                passage=PassageOut(
                    document=_out(p.document, names.get(p.document.instrument_id, "?")),
                    chunk_id=p.chunk_id,
                    position=p.position,
                    start_char=p.start_char,
                    end_char=p.end_char,
                    text=p.text,
                    score=p.score,
                    keyword_rank=p.keyword_rank,
                    vector_rank=p.vector_rank,
                    similarity=p.similarity,
                ),
            )
            for i, p in enumerate(out.sources, start=1)
        ],
        provider=out.provider,
        model=out.model,
        warnings=out.warnings,
        notes=out.retrieval.notes,
        disclaimer=ASK_DISCLAIMER,
    )
