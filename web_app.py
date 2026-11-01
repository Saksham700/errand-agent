from __future__ import annotations
import os
import json
import time
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from errand_agent.core.agent import ErrandAgent
from errand_agent.tools.mock_provider import MockProviderService
from errand_agent.core.tracer import ExecutionTracer
from errand_agent.core.llm.gemini_live import GeminiLiveLLM
from errand_agent.core.llm.scripted import ScriptedLLM
from evals.scenarios import run_all_scenarios

app = FastAPI(title="Errand Agent - Founding AI Engineer Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory agent instance for the dashboard session
service = MockProviderService(seed=42)
tracer = ExecutionTracer(run_id="web-dashboard-session")

api_key = os.environ.get("GEMINI_API_KEY")
if api_key and not api_key.startswith("your_"):
    llm = GeminiLiveLLM(api_key=api_key)
else:
    llm = ScriptedLLM()

agent = ErrandAgent(provider_service=service, tracer=tracer, llm=llm)

class ChatRequest(BaseModel):
    message: str
    scenario_override: Optional[str] = None  # "timeout", "price_change", "slot_taken"

@app.get("/", response_class=HTMLResponse)
def index():
    with open("web_static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/chat")
def chat(req: ChatRequest):
    if req.scenario_override == "timeout":
        service.force_book_outcome = "timeout_and_booked"
    elif req.scenario_override == "slot_taken":
        service.force_book_outcome = "slot_taken"
    elif req.scenario_override == "normal":
        service.force_book_outcome = None

    response_text = agent.handle_message(req.message)
    service.force_book_outcome = None

    approval_rec = agent.approval.active_record
    approval_info = None
    if approval_rec:
        approval_info = {
            "action": approval_rec.action,
            "provider_id": approval_rec.provider_id,
            "slot": approval_rec.slot,
            "price": approval_rec.price,
            "status": approval_rec.status.value,
            "void_reason": approval_rec.void_reason
        }

    return {
        "reply": response_text,
        "state": {
            "service": agent.workflow.state.service,
            "area": agent.workflow.state.area,
            "time_window": agent.workflow.state.time_window,
            "budget": agent.workflow.state.budget,
            "missing_fields": agent.workflow.get_missing_fields(),
            "active_hold": agent.workflow.state.active_hold.__dict__ if agent.workflow.state.active_hold else None
        },
        "approval": approval_info,
        "recent_events": [
            {
                "event_type": e.event_type,
                "payload": e.payload,
                "latency_ms": e.latency_ms,
                "tokens": e.tokens
            }
            for e in tracer.events[-8:]
        ]
    }

@app.get("/api/state")
def get_state():
    approval_rec = agent.approval.active_record
    approval_info = None
    if approval_rec:
        approval_info = {
            "action": approval_rec.action,
            "provider_id": approval_rec.provider_id,
            "slot": approval_rec.slot,
            "price": approval_rec.price,
            "status": approval_rec.status.value,
            "void_reason": approval_rec.void_reason
        }

    return {
        "workflow": {
            "service": agent.workflow.state.service,
            "area": agent.workflow.state.area,
            "time_window": agent.workflow.state.time_window,
            "budget": agent.workflow.state.budget,
            "missing_fields": agent.workflow.get_missing_fields(),
            "active_hold": agent.workflow.state.active_hold.__dict__ if agent.workflow.state.active_hold else None
        },
        "approval": approval_info,
        "memory": agent.memory.view_memory(),
        "total_events": len(tracer.events)
    }

@app.post("/api/reset")
def reset():
    global service, tracer, agent
    service = MockProviderService(seed=42)
    tracer = ExecutionTracer(run_id=f"web-session-{int(time.time())}")
    agent = ErrandAgent(provider_service=service, tracer=tracer, llm=llm)
    return {"status": "reset_successful"}

@app.get("/api/evals")
def get_evals():
    results = run_all_scenarios()
    return [
        {
            "name": r.name,
            "expected": r.expected,
            "actual": r.actual,
            "passed": r.passed,
            "notes": r.notes
        }
        for r in results
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=False)
