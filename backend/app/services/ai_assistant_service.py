"""The floating CRM copilot: a tool-emulation loop over Gemini.

Gemini has no native function-calling in this codebase (see gemini_client.py), so "tool use" is
emulated the same way the planner emulates its own decisions: the model is constrained to a JSON
schema and may set `action="use_tools"` to ask this service to run one or more of a small,
fixed tool catalog, whose results are appended to the prompt for a follow-up call. The loop caps
at `_MAX_ITERATIONS` calls so a confused model can never spin forever.

Read-only throughout: tools only ever query the CRM. The one thing the assistant can propose -
`knowledge_suggestion` - is never written automatically; app_knowledge_service.create_entry is
only ever called from the API layer once a human clicks "save".
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import ASSISTANT_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, AiAgentRun
from app.models.app_knowledge_entry import SOURCE_AI
from app.models.assistant_conversation import AssistantConversation
from app.models.assistant_message import ROLE_ASSISTANT, ROLE_USER, AssistantMessage
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_prompt_blocks, ai_reply_service, app_knowledge_service, gemini_client, search_service
from app.services.agent_run_recorder import AgentRunRecorder

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 10
_MAX_ITERATIONS = 3
_MAX_REQUESTS_PER_TURN = 4

# Shown when the model errors or the tool loop ends without an answer. Also the sentinel the run
# status is derived from, so it lives in one place.
_FALLBACK_ANSWER = "Sorry, I couldn't answer that right now - please try again."

_TOOL_CATALOG_BASE = (
    "- search_knowledge_base(query): search the app's how-it-works knowledge base.\n"
)
_TOOL_CATALOG_CRM = (
    "- search_crm(query, types?): substring-search tenants, communications, finance records, "
    "and other CRM entities. `types` optionally narrows to specific result types.\n"
    "- get_tenant_context(tenant_id): load one tenant's booking, payments, notes, and recent "
    "message history.\n"
)

ASSISTANT_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},  # "use_tools" | "answer"
        "requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "query": {"type": ["string", "null"]},
                    "types": {"type": "array", "items": {"type": "string"}},
                    "tenant_id": {"type": ["integer", "null"]},
                },
                "required": ["tool"],
            },
        },
        "answer": {"type": ["string", "null"]},
        "knowledge_suggestion": {
            "type": ["object", "null"],
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
        },
    },
    "required": ["action"],
}


def _render_screen_context(screen_context: dict | None) -> str:
    if not screen_context:
        return ""
    lines = []
    if screen_context.get("pathname"):
        lines.append(f"Route: {screen_context['pathname']}")
    if screen_context.get("title"):
        lines.append(f"Page title: {screen_context['title']}")
    if screen_context.get("tenantId"):
        lines.append(f"Tenant currently open: {screen_context['tenantId']}")
    visible_text = (screen_context.get("visibleText") or "").strip()
    if visible_text:
        lines.append(f"Visible page text:\n{visible_text}")
    return "\n".join(lines)


def _render_history(history: list[AssistantMessage]) -> str:
    if not history:
        return ""
    lines = [f"{'Staff' if m.role == ROLE_USER else 'Assistant'}: {m.content}" for m in history[-_HISTORY_LIMIT:]]
    return "\n".join(lines)


def _dispatch_tool(db: Session, request: dict, *, use_crm: bool) -> tuple[str, str]:
    """Run one tool request and return (heading_key, rendered result text)."""
    tool = str(request.get("tool") or "").strip()

    if tool == "search_knowledge_base":
        query = str(request.get("query") or "").strip()
        entries = app_knowledge_service.search(db, query)
        if not entries:
            return "ctx_knowledge", f"No knowledge base entries matched '{query}'."
        lines = [f"- {e.title}: {e.body}" for e in entries]
        return "ctx_knowledge", "\n".join(lines)

    if tool == "search_crm":
        if not use_crm:
            return "ctx_crm_search", "CRM search is turned off for this conversation."
        query = str(request.get("query") or "").strip()
        types = request.get("types") or None
        hits = search_service.search(db, query, types=types, per_type_limit=5)
        if not hits:
            return "ctx_crm_search", f"No CRM results matched '{query}'."
        lines = [f"- [{h.type}] {h.title} (tenant_id={h.tenant_id}): {h.snippet}" for h in hits]
        return "ctx_crm_search", "\n".join(lines)

    if tool == "get_tenant_context":
        if not use_crm:
            return "ctx_tenant", "CRM lookups are turned off for this conversation."
        tenant_id = request.get("tenant_id")
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first() if tenant_id else None
        if tenant is None:
            return "ctx_tenant", f"No tenant found with id {tenant_id!r}."
        parts = [
            ai_reply_service._build_beds24_context(tenant),
            ai_reply_service._build_payments_context(db, tenant),
            ai_reply_service._build_notes_context(tenant),
            ai_reply_service._build_history_context(db, tenant, 20),
        ]
        return "ctx_tenant", "\n\n".join(p for p in parts if p.strip())

    return "ctx_knowledge", f"Unknown tool '{tool}' - ignored."


def _build_prompt(
    profile: AiAgentProfile | None,
    blocks: dict[str, str],
    *,
    screen_context: dict | None,
    history: list[AssistantMessage],
    tool_results: list[tuple[str, str]],
    use_crm: bool,
    question: str,
) -> str:
    parts: list[str] = []

    preamble = (blocks.get("preamble") or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = (profile.instructions or "").strip() if profile is not None else ""
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    catalog = _TOOL_CATALOG_BASE + (_TOOL_CATALOG_CRM if use_crm else "")
    parts.append(ai_prompt_blocks.join(blocks["tool_catalog"], catalog.strip()))

    screen_text = _render_screen_context(screen_context)
    if screen_text:
        parts.append(ai_prompt_blocks.join(blocks["ctx_screen"], screen_text))

    for heading_key, text in tool_results:
        if text.strip():
            parts.append(ai_prompt_blocks.join(blocks.get(heading_key, ""), text))

    history_text = _render_history(history)
    if history_text:
        parts.append(ai_prompt_blocks.join(blocks["ctx_history"], history_text))

    parts.append(ai_prompt_blocks.join(blocks["ctx_question"], question))
    return "\n\n".join(p for p in parts if p.strip())


def list_conversations(db: Session, user_id: int) -> list[AssistantConversation]:
    return (
        db.query(AssistantConversation)
        .filter(AssistantConversation.user_id == user_id)
        .order_by(AssistantConversation.updated_at.desc())
        .all()
    )


def get_conversation(db: Session, conversation_id: int, user_id: int) -> AssistantConversation | None:
    return (
        db.query(AssistantConversation)
        .filter(AssistantConversation.id == conversation_id, AssistantConversation.user_id == user_id)
        .first()
    )


def create_conversation(db: Session, user_id: int, title: str | None = None) -> AssistantConversation:
    conversation = AssistantConversation(user_id=user_id, title=(title or "New chat").strip() or "New chat")
    db.add(conversation)
    db.flush()
    return conversation


def rename_conversation(db: Session, conversation: AssistantConversation, title: str) -> AssistantConversation:
    conversation.title = title.strip() or conversation.title
    db.flush()
    return conversation


def delete_conversation(db: Session, conversation: AssistantConversation) -> None:
    db.delete(conversation)


def list_messages(db: Session, conversation_id: int) -> list[AssistantMessage]:
    return (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.asc(), AssistantMessage.id.asc())
        .all()
    )


def _coerce_tenant_id(screen_context: dict | None) -> int | None:
    """The tenant currently open in the UI, when the chat was sent from a tenant screen."""
    if not screen_context:
        return None
    raw = screen_context.get("tenantId")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_run(db: Session, conversation: AssistantConversation, screen_context: dict | None) -> AiAgentRun:
    """Reuse this conversation's run so more questions append to it, or create it on first ask.

    Keeps one AiAgentRun per chat in the AI Planner Runs log rather than one per question.
    """
    if conversation.agent_run_id is not None:
        run = db.query(AiAgentRun).filter(AiAgentRun.id == conversation.agent_run_id).first()
        if run is not None:
            return run

    run = AiAgentRun(
        tenant_id=_coerce_tenant_id(screen_context),
        channel="assistant",
        mode="manual",
        status=STATUS_FAILED,
        created_by_user_id=conversation.user_id,
    )
    db.add(run)
    db.flush()
    conversation.agent_run_id = run.id
    return run


def ask(
    db: Session,
    conversation: AssistantConversation,
    question: str,
    *,
    screen_context: dict | None = None,
    use_crm: bool = False,
) -> AssistantMessage:
    """Answer one question in `conversation`, persisting both the question and the answer."""
    question = (question or "").strip()
    profile = ai_agent_orchestrator.resolve_profile(db, ASSISTANT_ROLE, None)
    blocks = ai_prompt_blocks.resolve_blocks(profile, ASSISTANT_ROLE)
    history = list_messages(db, conversation.id)
    generation_kwargs = ai_agent_orchestrator._generation_kwargs(profile)
    resolved_model = generation_kwargs.get("model") or gemini_client.GEMINI_MODEL

    run = _resolve_run(db, conversation, screen_context)
    recorder = AgentRunRecorder(run=run, db=db)

    tool_results: list[tuple[str, str]] = []
    tool_trace: list[dict] = []
    answer_text = _FALLBACK_ANSWER
    knowledge_suggestion: dict | None = None
    gemini_failed = False

    for _ in range(_MAX_ITERATIONS):
        prompt = _build_prompt(
            profile,
            blocks,
            screen_context=screen_context,
            history=history,
            tool_results=tool_results,
            use_crm=use_crm,
            question=question,
        )
        try:
            result = gemini_client.generate(prompt, response_schema=ASSISTANT_STEP_SCHEMA, **generation_kwargs)
        except gemini_client.GeminiClientError as exc:
            # Record the real upstream error (usually a transient Gemini 503) on the run and in
            # the logs, instead of silently swallowing it behind the generic fallback.
            gemini_failed = True
            logger.warning("assistant Gemini call failed for conversation %s: %s", conversation.id, exc)
            recorder.record("assistant", prompt=prompt, error=str(exc), model=resolved_model)
            break

        recorder.record("assistant", prompt=prompt, result=result)
        parsed = result.parsed or {}
        action = parsed.get("action")

        if action == "use_tools":
            requests = (parsed.get("requests") or [])[:_MAX_REQUESTS_PER_TURN]
            if not requests:
                answer_text = (parsed.get("answer") or "").strip() or answer_text
                break
            for request in requests:
                heading_key, text = _dispatch_tool(db, request, use_crm=use_crm)
                tool_results.append((heading_key, text))
                tool_trace.append({"tool": request.get("tool"), "args": request, "result": text})
            continue

        # action == "answer" (or anything unrecognised - treat as final so we never loop forever)
        answer_text = (parsed.get("answer") or "").strip() or answer_text
        suggestion = parsed.get("knowledge_suggestion")
        if isinstance(suggestion, dict) and (suggestion.get("title") or "").strip() and (suggestion.get("body") or "").strip():
            knowledge_suggestion = {"title": suggestion["title"].strip(), "body": suggestion["body"].strip()}
        break

    answered = answer_text != _FALLBACK_ANSWER
    if not answered and not gemini_failed:
        logger.warning(
            "assistant exhausted %s tool iterations without an answer for conversation %s",
            _MAX_ITERATIONS,
            conversation.id,
        )
    recorder.finish(STATUS_COMPLETED if answered else STATUS_FAILED)

    db.add(AssistantMessage(conversation_id=conversation.id, role=ROLE_USER, content=question))
    assistant_message = AssistantMessage(
        conversation_id=conversation.id,
        role=ROLE_ASSISTANT,
        content=answer_text,
        tool_trace={"steps": tool_trace, "knowledge_suggestion": knowledge_suggestion} if (tool_trace or knowledge_suggestion) else None,
    )
    db.add(assistant_message)

    if conversation.title in (None, "", "New chat") and question:
        conversation.title = question[:80]
    from sqlalchemy import func

    conversation.updated_at = func.now()

    db.flush()
    return assistant_message
