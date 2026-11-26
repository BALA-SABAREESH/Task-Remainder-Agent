from __future__ import annotations

import html
import os
import re
from typing import Any, Literal, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .storage import TaskPriority, TaskStore, dbms


# ===== LangChain Structured Output Schemas =====


class ExtractedTaskItem(BaseModel):
    task: str = Field(description="Concise actionable task title extracted from the document")
    priority: TaskPriority = Field(description="Task urgency: high, med, or low")
    tags: list[str] = Field(default_factory=list, description="1 to 3 short topic tags")
    ai_notes: str = Field(default="", description="Brief rationale or context from the document")
    entities: list[str] = Field(default_factory=list, description="Key entities, modules, or people referenced")


class ExtractedDocumentTasks(BaseModel):
    document_summary: str = Field(description="Short 1-2 sentence summary of the processed document")
    tasks: list[ExtractedTaskItem] = Field(
        default_factory=list, description="Actionable tasks extracted from the document"
    )


class IntentDecision(BaseModel):
    intent: Literal[
        "add",
        "show",
        "done",
        "delete",
        "clear_done",
        "validate",
        "process_doc",
        "ai_analyze",
        "exit",
        "unknown",
    ]
    task_text: Optional[str] = None
    task_index: Optional[int] = None
    priority: Optional[TaskPriority] = None


class AIAnalysisOutput(BaseModel):
    recommendation: str = Field(description="Concise actionable recommendation based on current tasks")
    focus_task: Optional[str] = Field(default=None, description="Highest-impact pending task to tackle next")
    risk_note: Optional[str] = Field(default=None, description="Bottleneck or overload observation if any")


# ===== LangGraph State =====


class LogEntry(TypedDict):
    text: str
    cls: str


class ToastPayload(TypedDict):
    msg: str
    icon: str


class AgentState(TypedDict, total=False):
    command: str
    document_text: Optional[str]
    added_display: Optional[str]
    intent: str
    args: str
    task_index: Optional[int]
    priority_override: Optional[TaskPriority]
    store_valid: bool
    validation_issues: list[str]
    logs: list[LogEntry]
    toast: Optional[ToastPayload]
    error: Optional[str]
    ai_used: bool
    exited: bool
    new_task_id: Optional[str]
    tasks_snapshot: list[dict[str, Any]]
    activity: list[int]
    stats: dict[str, Any]
    integrity: dict[str, Any]


# ===== Helpers =====


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "MY_GEMINI_API_KEY":
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Please add it in Settings > Secrets."
        )
    return ChatGoogleGenerativeAI(
        model="gemini-4-hydrogen",
        google_api_key=api_key,
        temperature=0.2,
    )


def _infer_priority_from_text(task_text: str) -> TaskPriority:
    lower = task_text.lower()
    if any(
        kw in lower
        for kw in (
            "urgent",
            "critical",
            "blocker",
            "security",
            "auth",
            "hotfix",
            "bug",
            "asap",
            "p0",
            "prod",
            "incident",
        )
    ):
        return "high"
    if any(
        kw in lower
        for kw in ("docs", "documentation", "cleanup", "refactor", "minor", "optional", "nice to have")
    ):
        return "low"
    return "med"


def _store_to_snapshot(store: TaskStore, new_task_id: Optional[str] = None) -> dict[str, Any]:
    tasks_snapshot = []
    for t in store.tasks:
        tasks_snapshot.append(
            {
                "id": t.id,
                "index": t.index,
                "task": t.task,
                "done": t.done,
                "priority": t.priority,
                "added": t.added,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
                "detail_file": t.detail_file,
                "source": t.source,
                "metadata": t.metadata.model_dump(mode="json"),
                "isNew": bool(new_task_id and t.id == new_task_id),
            }
        )
    return {
        "tasks_snapshot": tasks_snapshot,
        "activity": list(store.activity),
        "stats": store.stats.model_dump(mode="json"),
        "integrity": store.integrity.model_dump(mode="json"),
    }


# ===== LangGraph Nodes =====


def load_and_validate_node(state: AgentState) -> AgentState:
    store, report = dbms.validate_and_repair()
    logs: list[LogEntry] = list(state.get("logs") or [])
    if report.repaired and report.issues:
        logs.append(
            {
                "text": f'→ JSON integrity self-healed ({len(report.issues)} check(s))',
                "cls": "t-info",
            }
        )
    snap = _store_to_snapshot(store)
    return {
        "store_valid": report.valid,
        "validation_issues": report.issues,
        "logs": logs,
        **snap,
    }


def route_command_node(state: AgentState) -> AgentState:
    cmd = (state.get("command") or "").strip()
    doc_text = state.get("document_text")

    if doc_text and doc_text.strip():
        return {
            "intent": "process_doc",
            "args": doc_text.strip(),
        }

    if not cmd:
        return {"intent": "unknown", "args": ""}

    lower = cmd.lower()

    if lower.startswith("add "):
        return {"intent": "add", "args": cmd[4:].strip()}

    if lower == "add":
        return {"intent": "add", "args": ""}

    if lower == "show" or lower == "list" or lower == "ls":
        return {"intent": "show", "args": ""}

    if lower.startswith("done "):
        return {"intent": "done", "args": cmd[5:].strip()}

    for prefix in ("delete ", "del ", "rm ", "remove "):
        if lower.startswith(prefix):
            arg = cmd[len(prefix) :].strip()
            if arg.lower() in ("done", "completed", "all done"):
                return {"intent": "clear_done", "args": ""}
            return {"intent": "delete", "args": arg}

    if lower in ("clear done", "purge done", "delete done", "clean"):
        return {"intent": "clear_done", "args": ""}

    if lower in ("validate", "verify", "check", "integrity"):
        return {"intent": "validate", "args": ""}

    if lower.startswith("process "):
        return {"intent": "process_doc", "args": cmd[8:].strip()}

    if lower.startswith("doc "):
        return {"intent": "process_doc", "args": cmd[4:].strip()}

    if lower == "ai" or lower == "analyze":
        return {"intent": "ai_analyze", "args": ""}

    if lower == "exit" or lower == "quit":
        return {"intent": "exit", "args": ""}

    # Natural-language routing via LangChain + Gemini when input doesn't match a strict CLI prefix
    if len(cmd.split()) >= 2:
        try:
            llm = _get_llm()
            structured_llm = llm.with_structured_output(IntentDecision)
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are the NeuralTask LangGraph command router. Map the user's request to one intent: "
                        "add (create a task), show (list tasks), done (complete task #), delete (delete task #), "
                        "clear_done (delete all completed tasks), validate (validate local JSON files), "
                        "process_doc (extract tasks from a complex document or multi-step description), "
                        "ai_analyze (analyze task productivity), exit, or unknown.",
                    ),
                    ("human", "{input}"),
                ]
            )
            chain = prompt | structured_llm
            decision: IntentDecision = chain.invoke({"input": cmd})
            if decision.intent != "unknown":
                args = decision.task_text or (
                    str(decision.task_index) if decision.task_index is not None else cmd
                )
                return {
                    "intent": decision.intent,
                    "args": args,
                    "task_index": decision.task_index,
                    "priority_override": decision.priority,
                    "ai_used": True,
                }
        except Exception:
            # Fall through to standard unknown command response if key is missing or intent unclear
            pass

    return {"intent": "unknown", "args": cmd}


def route_edge(state: AgentState) -> str:
    intent = state.get("intent", "unknown")
    if intent in ("add", "show", "done", "delete", "clear_done"):
        return "crud"
    if intent == "process_doc":
        return "process_doc"
    if intent == "ai_analyze":
        return "ai_analyze"
    if intent == "validate":
        return "validate"
    if intent == "exit":
        return "exit"
    return "unknown"


def task_crud_node(state: AgentState) -> AgentState:
    intent = state.get("intent")
    args = (state.get("args") or "").strip()
    logs: list[LogEntry] = list(state.get("logs") or [])
    toast: Optional[ToastPayload] = None
    new_task_id: Optional[str] = None

    if intent == "add":
        if not args:
            logs.append({"text": "→ Error: please provide a task name.", "cls": "t-err"})
            return {"logs": logs, "error": "missing task name"}

        priority = state.get("priority_override") or _infer_priority_from_text(args)
        store, created = dbms.add_task(
            task_text=args,
            priority=priority,
            added=state.get("added_display"),
            source="langchain-router" if state.get("ai_used") else "command",
        )
        new_task_id = created.id
        logs.append(
            {
                "text": (
                    f'→ Task added: <span style="color:var(--text)">"{_esc(created.task)}"</span>  '
                    f'<span style="color:var(--text-dim)">[priority: {created.priority} · saved: {created.id}.json]</span>'
                ),
                "cls": "t-res",
            }
        )
        toast = {"msg": "Task added", "icon": "➕"}
        return {
            "logs": logs,
            "toast": toast,
            "new_task_id": new_task_id,
            **_store_to_snapshot(store, new_task_id=new_task_id),
        }

    if intent == "show":
        store = dbms.load_store()
        if not store.tasks:
            logs.append({"text": "→ No tasks in local JSON store.", "cls": "t-res"})
        else:
            for t in store.tasks:
                status_str = "✔ done" if t.done else "✘ pending"
                logs.append(
                    {
                        "text": (
                            f"  {str(t.index).zfill(2)}. {_esc(t.task)} "
                            f'<span style="color:var(--text-dim)">[{status_str} · {t.priority} · {t.id}]</span>'
                        ),
                        "cls": "t-res",
                    }
                )
        return {"logs": logs, **_store_to_snapshot(store)}

    if intent == "done":
        num = state.get("task_index")
        if num is None:
            match = re.search(r"\d+", args)
            num = int(match.group(0)) if match else -1

        try:
            store, updated, already_done = dbms.complete_task(num)
        except IndexError:
            logs.append({"text": "→ Error: invalid task number.", "cls": "t-err"})
            return {"logs": logs, "error": "invalid task number"}

        if already_done:
            logs.append({"text": "→ Task already completed.", "cls": "t-err"})
        else:
            logs.append(
                {
                    "text": (
                        f'→ Task {num} marked as <span style="color:var(--cyan)">completed</span> ✓ '
                        f'<span style="color:var(--text-dim)">[updated {updated.id}.json]</span>'
                    ),
                    "cls": "t-res",
                }
            )
            toast = {"msg": "Task completed", "icon": "✅"}
        return {"logs": logs, "toast": toast, **_store_to_snapshot(store)}

    if intent == "delete":
        num = state.get("task_index")
        if num is None:
            match = re.search(r"\d+", args)
            num = int(match.group(0)) if match else -1

        try:
            store, removed = dbms.delete_task(num)
        except IndexError:
            logs.append({"text": "→ Error: invalid task number for delete.", "cls": "t-err"})
            return {"logs": logs, "error": "invalid task number"}

        logs.append(
            {
                "text": (
                    f'→ Deleted task {num}: <span style="color:var(--text)">"{_esc(removed.task)}"</span> '
                    f'<span style="color:var(--text-dim)">[removed {removed.id}.json · JSON re-indexed]</span>'
                ),
                "cls": "t-res",
            }
        )
        toast = {"msg": f"Removed: {removed.task[:24]}", "icon": "✕"}
        return {"logs": logs, "toast": toast, **_store_to_snapshot(store)}

    if intent == "clear_done":
        store, removed = dbms.delete_completed_tasks()
        if not removed:
            logs.append({"text": "→ No completed tasks to remove.", "cls": "t-info"})
        else:
            logs.append(
                {
                    "text": (
                        f"→ Removed {len(removed)} completed task(s) from tasks.json "
                        f"and deleted {len(removed)} detail record file(s)."
                    ),
                    "cls": "t-res",
                }
            )
            toast = {"msg": f"Cleared {len(removed)} done", "icon": "🧹"}
        return {"logs": logs, "toast": toast, **_store_to_snapshot(store)}

    return {"logs": logs}


def document_processor_node(state: AgentState) -> AgentState:
    raw_doc = (state.get("args") or state.get("document_text") or "").strip()
    logs: list[LogEntry] = list(state.get("logs") or [])
    if not raw_doc:
        logs.append({"text": "→ Error: provide document text after 'process '.", "cls": "t-err"})
        return {"logs": logs, "error": "empty document"}

    try:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_text(raw_doc)
        docs = [
            Document(page_content=chunk, metadata={"chunk_index": i, "total_chunks": len(chunks)})
            for i, chunk in enumerate(chunks)
        ]

        llm = _get_llm()
        structured_llm = llm.with_structured_output(ExtractedDocumentTasks)
        joined_chunks = "\n\n".join(
            f"[Chunk {d.metadata['chunk_index'] + 1}/{len(docs)}]\n{d.page_content}" for d in docs
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a LangChain document intelligence processor for NeuralTask. "
                    "Extract concise, actionable tasks from the chunked document below. "
                    "Assign realistic priorities (high, med, low), short topic tags, key entities, and brief notes.",
                ),
                ("human", "{document}"),
            ]
        )
        chain = prompt | structured_llm
        extracted: ExtractedDocumentTasks = chain.invoke({"document": joined_chunks})

        if not extracted.tasks:
            logs.append(
                {
                    "text": f"→ Document processed ({len(docs)} chunk(s)), no actionable tasks found.",
                    "cls": "t-ai",
                }
            )
            return {"logs": logs, "ai_used": True}

        latest_store: Optional[TaskStore] = None
        last_id: Optional[str] = None
        for item in extracted.tasks:
            latest_store, created = dbms.add_task(
                task_text=item.task,
                priority=item.priority,
                added=state.get("added_display"),
                source="langchain-document-processor",
                tags=item.tags,
                ai_notes=item.ai_notes or extracted.document_summary,
                document_source="terminal-document",
                document_chunks=[d.page_content for d in docs],
                extracted_entities=item.entities,
            )
            last_id = created.id

        logs.append(
            {
                "text": (
                    f'→ 📄 <span style="color:var(--cyan)">LangChain Document Processed</span> '
                    f"({len(docs)} chunk(s) · {len(extracted.tasks)} task(s) stored in JSON)"
                ),
                "cls": "t-ai",
            }
        )
        logs.append(
            {
                "text": f"  ├─ Summary: {_esc(extracted.document_summary)}",
                "cls": "t-ai",
            }
        )
        for idx, item in enumerate(extracted.tasks, start=1):
            branch = "└─" if idx == len(extracted.tasks) else "├─"
            logs.append(
                {
                    "text": f"  {branch} Added [{item.priority}]: {_esc(item.task)}",
                    "cls": "t-res",
                }
            )

        toast: ToastPayload = {"msg": f"Extracted {len(extracted.tasks)} tasks", "icon": "📄"}
        snap = _store_to_snapshot(latest_store, new_task_id=last_id) if latest_store else {}
        return {
            "logs": logs,
            "toast": toast,
            "ai_used": True,
            "new_task_id": last_id,
            **snap,
        }
    except Exception as exc:
        logs.append({"text": f"→ Document processing error: {_esc(str(exc))}", "cls": "t-err"})
        return {"logs": logs, "error": str(exc)}


def ai_analyzer_node(state: AgentState) -> AgentState:
    store = dbms.load_store()
    logs: list[LogEntry] = list(state.get("logs") or [])

    total = store.stats.total
    done = store.stats.completed
    pct = store.stats.completion_rate

    logs.append(
        {
            "text": '→ 🤖 <span style="color:var(--amber)">NeuralTask AI Analysis (LangGraph)</span>',
            "cls": "t-ai",
        }
    )
    logs.append({"text": f"  ├─ Total tasks: {total}", "cls": "t-ai"})
    logs.append({"text": f"  ├─ Completion: {pct}% ({done}/{total})", "cls": "t-ai"})
    logs.append({"text": f"  ├─ AI Score: {store.stats.ai_score}", "cls": "t-ai"})
    logs.append(
        {
            "text": f"  ├─ JSON Integrity: valid · sha256:{store.integrity.checksum[:12]}…",
            "cls": "t-ai",
        }
    )

    try:
        llm = _get_llm()
        structured_llm = llm.with_structured_output(AIAnalysisOutput)
        task_summary = "\n".join(
            f"- [{t.index}] ({t.priority}, {'done' if t.done else 'pending'}) {t.task}"
            for t in store.tasks
        ) or "No tasks currently stored."
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are NeuralTask's LangGraph AI productivity strategist. "
                    "Analyze the user's persisted JSON tasks and provide one sharp recommendation.",
                ),
                ("human", "Tasks:\n{tasks}\nStats: {completed}/{total} completed ({rate}%)."),
            ]
        )
        chain = prompt | structured_llm
        analysis: AIAnalysisOutput = chain.invoke(
            {
                "tasks": task_summary,
                "completed": done,
                "total": total,
                "rate": pct,
            }
        )
        if analysis.focus_task:
            logs.append({"text": f"  ├─ Next Focus: {_esc(analysis.focus_task)}", "cls": "t-ai"})
        logs.append({"text": f"  └─ Recommendation: {_esc(analysis.recommendation)}", "cls": "t-ai"})
        return {"logs": logs, "ai_used": True, **_store_to_snapshot(store)}
    except Exception as exc:
        logs.append(
            {
                "text": f"  └─ Gemini AI Insight unavailable: {_esc(str(exc))}",
                "cls": "t-err",
            }
        )
        return {"logs": logs, "error": str(exc), **_store_to_snapshot(store)}


def validate_only_node(state: AgentState) -> AgentState:
    store, report = dbms.validate_and_repair()
    logs: list[LogEntry] = list(state.get("logs") or [])
    logs.append(
        {
            "text": (
                f'→ 🛡️ <span style="color:var(--cyan)">JSON File Integrity Verified</span> '
                f"[records: {report.record_count} · sha256:{report.checksum[:12]}…]"
            ),
            "cls": "t-res",
        }
    )
    if report.issues:
        for issue in report.issues:
            logs.append({"text": f"  ├─ Repaired: {_esc(issue)}", "cls": "t-info"})
    else:
        logs.append({"text": "  └─ All JSON schemas & detail files consistent.", "cls": "t-res"})
    return {
        "logs": logs,
        "toast": {"msg": "JSON validated", "icon": "✓"},
        **_store_to_snapshot(store),
    }


def integrity_commit_node(state: AgentState) -> AgentState:
    store, report = dbms.validate_and_repair()
    snap = _store_to_snapshot(store, new_task_id=state.get("new_task_id"))
    return {
        "store_valid": report.valid,
        "validation_issues": report.issues,
        **snap,
    }


def exit_node(state: AgentState) -> AgentState:
    logs: list[LogEntry] = list(state.get("logs") or [])
    logs.append({"text": "→ Goodbye! Agent shutting down gracefully.", "cls": "t-info"})
    return {
        "logs": logs,
        "toast": {"msg": "Agent exited", "icon": "⏻"},
        "exited": True,
    }


def unknown_node(state: AgentState) -> AgentState:
    logs: list[LogEntry] = list(state.get("logs") or [])
    logs.append(
        {
            "text": (
                '→ Unknown command. Try: <span style="color:var(--violet-light)">'
                "add / show / done &lt;n&gt; / delete &lt;n&gt; / process &lt;doc&gt; / validate / ai / exit"
                "</span>"
            ),
            "cls": "t-err",
        }
    )
    return {"logs": logs}


def build_workflow():
    graph = StateGraph(AgentState)

    graph.add_node("load_and_validate", load_and_validate_node)
    graph.add_node("route_command", route_command_node)
    graph.add_node("task_crud", task_crud_node)
    graph.add_node("document_processor", document_processor_node)
    graph.add_node("ai_analyzer", ai_analyzer_node)
    graph.add_node("validate_only", validate_only_node)
    graph.add_node("integrity_commit", integrity_commit_node)
    graph.add_node("exit_handler", exit_node)
    graph.add_node("unknown_handler", unknown_node)

    graph.add_edge(START, "load_and_validate")
    graph.add_edge("load_and_validate", "route_command")
    graph.add_conditional_edges(
        "route_command",
        route_edge,
        {
            "crud": "task_crud",
            "process_doc": "document_processor",
            "ai_analyze": "ai_analyzer",
            "validate": "validate_only",
            "exit": "exit_handler",
            "unknown": "unknown_handler",
        },
    )

    graph.add_edge("task_crud", "integrity_commit")
    graph.add_edge("document_processor", "integrity_commit")
    graph.add_edge("ai_analyzer", "integrity_commit")
    graph.add_edge("validate_only", "integrity_commit")
    graph.add_edge("integrity_commit", END)
    graph.add_edge("exit_handler", END)
    graph.add_edge("unknown_handler", END)

    return graph.compile()


agent_graph = build_workflow()
