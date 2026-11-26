from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .storage import dbms
from .workflow import _store_to_snapshot, agent_graph

app = FastAPI(title="NeuralTask LangGraph Engine", version="1.0.0")


class CommandRequest(BaseModel):
    command: str
    added_display: Optional[str] = None


class DocumentRequest(BaseModel):
    document_text: str
    added_display: Optional[str] = None


class ActionRequest(BaseModel):
    added_display: Optional[str] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "langgraph-json-dbms"}


@app.get("/api/tasks")
def get_tasks():
    store, report = dbms.validate_and_repair()
    snap = _store_to_snapshot(store)
    return {
        "tasks": snap["tasks_snapshot"],
        "activity": snap["activity"],
        "stats": snap["stats"],
        "integrity": snap["integrity"],
        "validation_report": report.model_dump(mode="json"),
    }


@app.post("/api/command")
def run_command(payload: CommandRequest):
    result = agent_graph.invoke(
        {
            "command": payload.command,
            "added_display": payload.added_display,
        }
    )
    return {
        "intent": result.get("intent", "unknown"),
        "logs": result.get("logs", []),
        "toast": result.get("toast"),
        "error": result.get("error"),
        "exited": bool(result.get("exited", False)),
        "ai_used": bool(result.get("ai_used", False)),
        "tasks": result.get("tasks_snapshot", []),
        "activity": result.get("activity", [0, 0, 0, 0, 0, 0, 0]),
        "stats": result.get("stats", {}),
        "integrity": result.get("integrity", {}),
    }


@app.post("/api/process-document")
def process_document(payload: DocumentRequest):
    if not payload.document_text.strip():
        raise HTTPException(status_code=400, detail="Document text is required")
    result = agent_graph.invoke(
        {
            "command": f"process {payload.document_text}",
            "document_text": payload.document_text,
            "added_display": payload.added_display,
        }
    )
    return {
        "intent": result.get("intent", "process_doc"),
        "logs": result.get("logs", []),
        "toast": result.get("toast"),
        "error": result.get("error"),
        "tasks": result.get("tasks_snapshot", []),
        "activity": result.get("activity", [0, 0, 0, 0, 0, 0, 0]),
        "stats": result.get("stats", {}),
        "integrity": result.get("integrity", {}),
    }


@app.post("/api/tasks/{index}/done")
def mark_task_done(index: int, payload: Optional[ActionRequest] = None):
    result = agent_graph.invoke(
        {
            "command": f"done {index}",
            "added_display": payload.added_display if payload else None,
        }
    )
    if result.get("error") == "invalid task number":
        raise HTTPException(status_code=404, detail="Invalid task number")
    return {
        "logs": result.get("logs", []),
        "toast": result.get("toast"),
        "tasks": result.get("tasks_snapshot", []),
        "activity": result.get("activity", [0, 0, 0, 0, 0, 0, 0]),
        "stats": result.get("stats", {}),
        "integrity": result.get("integrity", {}),
    }


@app.delete("/api/tasks/{index}")
def remove_task(index: int):
    result = agent_graph.invoke({"command": f"delete {index}"})
    if result.get("error") == "invalid task number":
        raise HTTPException(status_code=404, detail="Invalid task number")
    return {
        "logs": result.get("logs", []),
        "toast": result.get("toast"),
        "tasks": result.get("tasks_snapshot", []),
        "activity": result.get("activity", [0, 0, 0, 0, 0, 0, 0]),
        "stats": result.get("stats", {}),
        "integrity": result.get("integrity", {}),
    }


@app.post("/api/validate")
def validate_json_store():
    result = agent_graph.invoke({"command": "validate"})
    return {
        "logs": result.get("logs", []),
        "toast": result.get("toast"),
        "tasks": result.get("tasks_snapshot", []),
        "activity": result.get("activity", [0, 0, 0, 0, 0, 0, 0]),
        "stats": result.get("stats", {}),
        "integrity": result.get("integrity", {}),
    }
