# Errand Agent - Founding AI Engineer Assignment

An offline, deterministic, code-governed AI agent that books, reschedules, and cancels home-service errands against a mocked provider API — with zero double-booking, code-enforced approval verification, untrusted prompt injection defense, and resilient network recovery.

---

## Quickstart (Run and Test in 3 Commands)

```bash
# 1. Create and activate virtual environment
uv venv .venv && .\.venv\Scripts\activate

# 2. Install dependencies (pytest & requests)
uv pip install pytest requests

# 3. Run all unit tests and 18 automated offline evals
python -m pytest tests && python -m evals.runner
```

---

## Interactive Demo & Recording CLI

To run the interactive terminal demo (with real-time side-by-side chat & execution trace logs):

```bash
python cli.py
```

### Demo Shortcut Commands:
- Type natural queries: `"Find a plumber for my kitchen tap this week, mornings only, under 1500."`
- `/demo happy`: Runs an end-to-end booking flow showing code approval verification.
- `/demo injection`: Demonstrates provider review containing `SYSTEM OVERRIDE` prompt injection safely quarantined as passive data without compromising execution.
- `/demo timeout`: Triggers a network timeout and shows authoritative verification via `get_booking_status` with zero duplicate bookings.
- `/memory`: Displays persisted stated vs. unconfirmed inferred memory facts.
- `/quit`: Exit the demo.

---

## Must-Haves Implementation Summary

| # | Requirement | Implementation & Proof |
|---|---|---|
| 1 | **Explicit Workflow State** | `WorkflowManager` tracks `service`, `area`, `time_window`, `budget`, `preferences`. Asks strictly for missing attributes. Single-detail corrections preserve all existing facts. Proven in `tests/test_workflow.py` and Scenario 14. |
| 2 | **Approval Enforced by Code** | `ApprovalRecord` validated by `verify_and_consume()` in Python code. Any deviation in provider, slot, or price voids approval immediately (`ApprovalVoidError`). Proven in `tests/test_approval.py` and Scenarios 3 & 4. |
| 3 | **Booking Correctness & Recovery** | Deterministic SHA-256 idempotency keys. On timeout, checks `get_booking_status()` before retrying. Never claims unverified success. Journaling survives restarts mid-booking. Proven in `tests/test_idempotency_recovery.py` and Scenarios 5, 6 & 15. |
| 4 | **Untrusted Tool Output Defense** | Reviews and descriptions isolated inside boundary tags. Injections are quarantined and logged in security traces. Invariant: reviews cannot alter permissions or bypass approval. Proven in `tests/test_prompt_injection.py` and Scenario 2. |
| 5 | **Bounded Execution** | Hard caps on turns (10), tool calls (15), and wall-clock duration (30s) via `ExecutionBudget`. Every exit ends with a polite user-facing message. Proven in Scenarios 16 & 17. |
| 6 | **Persistent Memory** | Stated facts (`source=STATED`) persist across sessions. Inferred facts require explicit confirmation. Forgotten facts are tombstoned and permanently blocked from reuse. Proven in `tests/test_memory.py` and Scenarios 11, 12 & 13. |
| 7 | **Structured Observability (Traces)** | Complete event traces per run (`ExecutionTracer`): state transitions, model calls, tool calls/results, latency, tokens, cost. Automatic regex scrubbing of all secrets. Raw trace generated at `TRACE_TIMEOUT_AFTER_SUCCESS.json`. |
| 8 | **Automated Eval Suite** | 18 reproducible automated scenarios (minimum 15 required) with simulated users. Asserts code invariants. Automatically generates `EVAL_REPORT.md`. |

---

## Nice-To-Have: Proactive Follow-up

- **Implemented**: `ProactiveFollowUpHandler` in `errand_agent/core/proactive.py`.
- When a provider cancels an existing booking, the agent automatically detects it, finds an alternative top-rated provider in the same area, holds the replacement slot, and presents the option to the user for explicit approval.
- **Invariant**: The agent **never** automatically books the replacement without explicit user confirmation. Proven in Scenario 18.

---

## Project Structure & Deliverables

- `errand_agent/`: Core package
  - `models.py`: Data models (`ApprovalRecord`, `WorkflowState`, `Provider`, `Booking`, `TraceEvent`)
  - `tools/mock_provider.py`: Mock provider API with fixed contract & seeded error modes
  - `core/approval.py`: Code-enforced approval verification
  - `core/workflow.py`: Missing facts tracker & explicit state manager
  - `core/idempotency.py`: SHA-256 key generation & timeout recovery journal
  - `core/security.py`: Prompt injection quarantine & sanitization
  - `core/limits.py`: Turn, tool-call, and wall-clock bounded execution
  - `core/memory.py`: Persistent memory with stated/inferred guards and tombstones
  - `core/tracer.py`: Structured telemetry & secret redaction
  - `core/agent.py`: Central ErrandAgent orchestrator
  - `core/proactive.py`: Proactive cancellation & replacement flow
- `evals/`:
  - `scenarios.py`: 18 automated reproducible scenarios
  - `runner.py`: Eval test runner and markdown generator
- `tests/`: Pytest unit test suite
- `DESIGN_NOTE.md`: Architectural note, state model, timeout recovery excerpt, 100× scalability analysis
- `BUGS_AND_REGRESSIONS.md`: 3 real bugs encountered, root cause analysis, fixes, and regression tests
- `EVAL_REPORT.md`: Auto-generated evaluation matrix
- `TRACE_TIMEOUT_AFTER_SUCCESS.json`: Raw execution trace of timeout recovery
- `cli.py`: Interactive demo CLI
