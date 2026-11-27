"""`/v1/ai` (A8.2, A8.3): what the server's model may draft.

- `GET /v1/ai/status` (public): whether a provider is set up, and which.
- `POST /v1/ai/rule` (signed in, 10 a minute): plain English to Rule DSL.
  The draft is checked by the same code as `/v1/rules/check`; nothing runs.
  409 when no provider is set up; 502 when the provider fails.
- `POST /v1/ai/ask` (signed in, 10 a minute; A8.5, M11.2): a question about
  stored documents, answered from A8.4's passages with citations checked.
  409 without a provider, 502 when it fails, 404 an unknown ticker.
- `/v1/ai/keys` (signed in; A8.7 BYOK): `GET` lists the caller's saved keys
  (never the key), `PUT /{provider}` saves one encrypted, `DELETE /{provider}`
  removes it. 409 while `APP_ENCRYPTION_KEY` is unset. `/rule` and `/ask`
  take `provider: server | openai_compatible`.
- `POST /v1/ai/extract` (signed in, 5 a minute; A9.10, M11.3): reported
  figures out of a stored document, each kept only when its quote is in the
  text and its value in the quote.
- `POST /v1/ai/grid` (signed in, 2 a minute; A9.11, M11.4): up to 5 companies
  by 3 questions, each cell a copilot answer from that company's documents.
- `POST /v1/ai/debate` (signed in, 5 a minute; A9.11, M11.5): the case for and
  the case against one company on a topic, from the same passages.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.routers.documents import _instrument, _kind, _naive, _out, _public_doc, _tickers
from stockviz.schemas import (
    AiKeyIn,
    AiKeyOut,
    AiKeysOut,
    AiRuleAttemptOut,
    AiRuleIn,
    AiRuleOut,
    AiStatusOut,
    AnswerCheckOut,
    AskIn,
    AskOut,
    AskSourceOut,
    DebateIn,
    DebateOut,
    ExtractIn,
    ExtractOut,
    FigureOut,
    GridCellOut,
    GridIn,
    GridOut,
    PassageOut,
)
from stockviz.services.ai import copilot
from stockviz.services.ai import extract as ai_extract
from stockviz.services.ai import keys as ai_keys
from stockviz.services.ai import research as ai_research
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
    settings = get_settings()
    available = ai_keys.keys_available(settings)
    try:
        provider = provider_from_settings(settings)
    except AiNotConfigured as exc:
        return AiStatusOut(configured=False, reason=str(exc), keys_available=available)
    return AiStatusOut(
        configured=True, provider=provider.name, model=provider.model, keys_available=available
    )


SessionDep = Annotated[Session, Depends(get_session)]


def _provider(session: Session, user_id: int, choice: str):
    try:
        if choice == "server":
            return provider_from_settings(get_settings())
        return ai_keys.provider_for(session, get_settings(), user_id, choice)
    except (AiNotConfigured, ai_keys.KeysOff) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ai_keys.KeyMissing as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ai_keys.KeyError_ as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/rule", response_model=AiRuleOut)
@limiter.limit("10/minute")
def ai_rule(request: Request, body: AiRuleIn, user_id: UserIdDep, session: SessionDep) -> AiRuleOut:
    del request
    provider = _provider(session, user_id, body.provider)
    try:
        out = ai_rules.translate(provider, body.text, timeframe=body.timeframe)
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
    session: SessionDep,
) -> AskOut:
    del request
    iid = _instrument(session, body.ticker)[1] if body.ticker else None
    when = _naive(body.as_of)
    settings = get_settings()
    provider = _provider(session, user_id, body.provider)
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


KEYS_NOTE = (
    "Keys are encrypted on the server and never shown again; only their last four "
    "characters are. Each request you make with your key is billed to your account "
    "with that provider."
)


def _key_out(k: ai_keys.SavedKey) -> AiKeyOut:
    return AiKeyOut(
        provider=k.provider,
        model=k.model,
        base_url=k.base_url,
        key_last4=k.key_last4,
        updated_at=k.updated_at,
    )


@router.get("/keys", response_model=AiKeysOut)
def list_ai_keys(user_id: UserIdDep, session: SessionDep) -> AiKeysOut:
    return AiKeysOut(
        available=ai_keys.keys_available(get_settings()),
        keys=[_key_out(k) for k in ai_keys.list_keys(session, user_id)],
        providers=list(ai_keys.USABLE_PROVIDERS),
        held=ai_keys.HELD,
        note=KEYS_NOTE,
    )


@router.put("/keys/{provider}", response_model=AiKeyOut)
@limiter.limit("10/minute")
def save_ai_key(
    request: Request, provider: str, body: AiKeyIn, user_id: UserIdDep, session: SessionDep
) -> AiKeyOut:
    del request
    try:
        saved = ai_keys.save_key(
            session, get_settings(), user_id, provider,
            api_key=body.api_key, model=body.model, base_url=body.base_url,
        )  # fmt: skip
    except ai_keys.KeysOff as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ai_keys.KeyError_ as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _key_out(saved)


@router.delete("/keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_key(provider: str, user_id: UserIdDep, session: SessionDep) -> Response:
    try:
        ai_keys.delete_key(session, user_id, provider)
    except ai_keys.KeyMissing as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


EXTRACT_METHOD = (
    "The model read up to 8 passages of the document that contain a digit. A figure is kept "
    "only when its quote appears in the passages word for word and every number in its value "
    "appears in that quote; the rest are dropped and counted by reason."
)
EXTRACT_DISCLAIMER = (
    "Figures copied out by a model and checked against the text, not against the company's "
    "accounts. Read each in its quote. Not investment advice."
)


@router.post("/extract", response_model=ExtractOut)
@limiter.limit("5/minute")
def ai_extract_figures(
    request: Request, body: ExtractIn, user_id: UserIdDep, session: SessionDep
) -> ExtractOut:
    del request
    doc = _public_doc(session, body.document_id)
    provider = _provider(session, user_id, body.provider)
    try:
        out = ai_extract.extract(session, provider, doc.id or 0)
    except AiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    positions = {c.id: c.position for c in out.passages}
    ticker = _tickers(session, {doc.instrument_id}).get(doc.instrument_id, "?")
    return ExtractOut(
        document=_out(doc, ticker),
        figures=[
            FigureOut(
                metric=f.metric,
                value=f.value,
                unit=f.unit,
                period=f.period,
                quote=f.quote,
                chunk_id=f.chunk_id,
                position=positions.get(f.chunk_id, 0),
            )
            for f in out.figures
        ],
        passages_read=len(out.passages),
        dropped=out.dropped,
        provider=out.provider,
        model=out.model,
        method=EXTRACT_METHOD,
        disclaimer=EXTRACT_DISCLAIMER,
    )


RESEARCH_DISCLAIMER = (
    "Written by a model only from the passages listed under each answer. Check every point "
    "against its source. Neither side of a debate is a recommendation; not investment advice."
)


def _passage_out(session: Session, p, *, max_chars: int | None = None) -> PassageOut:
    names = _tickers(session, {p.document.instrument_id})
    text = p.text if max_chars is None or len(p.text) <= max_chars else p.text[:max_chars] + "…"
    return PassageOut(
        document=_out(p.document, names.get(p.document.instrument_id, "?")),
        chunk_id=p.chunk_id,
        position=p.position,
        start_char=p.start_char,
        end_char=p.end_char,
        text=text,
        score=p.score,
        keyword_rank=p.keyword_rank,
        vector_rank=p.vector_rank,
        similarity=p.similarity,
    )


def _checked(
    session: Session, out: copilot.CopilotAnswer, *, max_chars: int | None = None
) -> AnswerCheckOut:
    check = out.check
    cited = set(check.cited) if check else set()
    return AnswerCheckOut(
        answer=out.answer or "",
        grounded=bool(check and check.grounded),
        cited=sorted(cited),
        invalid_citations=check.invalid if check else [],
        uncited_sentences=check.uncited_sentences if check else 0,
        warnings=out.warnings,
        sources=[
            AskSourceOut(
                n=i, cited=i in cited, passage=_passage_out(session, p, max_chars=max_chars)
            )
            for i, p in enumerate(out.sources, start=1)
        ],
    )


@router.post("/grid", response_model=GridOut)
@limiter.limit("2/minute")
def ai_grid(request: Request, body: GridIn, user_id: UserIdDep, session: SessionDep) -> GridOut:
    del request
    tickers = list(dict.fromkeys(t.strip().upper() for t in body.tickers if t.strip()))
    questions = [" ".join(q.split()) for q in body.questions]
    if not tickers:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name at least one symbol")
    if any(not 5 <= len(q) <= 300 for q in questions):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "each question needs 5 to 300 characters"
        )
    companies = [(t, _instrument(session, t)[1]) for t in tickers]
    when = _naive(body.as_of)
    settings = get_settings()
    provider = _provider(session, user_id, body.provider)
    try:
        cells = ai_research.grid(
            session, provider, companies, questions, as_of=when,
            ticker_names=lambda ids: _tickers(session, ids),
            embedder=embedder_from_settings(settings),
        )  # fmt: skip
    except AiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    calls = sum(1 for c in cells if c.answer.model)
    return GridOut(
        as_of=when,
        tickers=tickers,
        questions=questions,
        cells=[
            GridCellOut(
                ticker=c.ticker,
                question=c.question,
                result=_checked(session, c.answer, max_chars=600),
            )
            for c in cells
        ],
        model_calls=calls,
        provider=provider.name,
        model=provider.model,
        disclaimer=RESEARCH_DISCLAIMER,
    )


@router.post("/debate", response_model=DebateOut)
@limiter.limit("5/minute")
def ai_debate(
    request: Request, body: DebateIn, user_id: UserIdDep, session: SessionDep
) -> DebateOut:
    del request
    ticker, iid = _instrument(session, body.ticker)
    when = _naive(body.as_of)
    settings = get_settings()
    provider = _provider(session, user_id, body.provider)
    try:
        out = ai_research.debate(
            session, provider, ticker, iid, body.topic, as_of=when,
            ticker_names=lambda ids: _tickers(session, ids),
            embedder=embedder_from_settings(settings),
        )  # fmt: skip
    except AiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return DebateOut(
        ticker=ticker,
        topic=out.topic,
        as_of=when,
        retrieval_mode=out.retrieval.mode,
        case_for=_checked(session, out.case_for),
        case_against=_checked(session, out.case_against),
        provider=provider.name,
        model=provider.model,
        disclaimer=RESEARCH_DISCLAIMER,
    )
