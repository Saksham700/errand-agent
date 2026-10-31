from __future__ import annotations
import os
import sys
import json
import time
from errand_agent.core.agent import ErrandAgent
from errand_agent.tools.mock_provider import MockProviderService
from errand_agent.core.tracer import ExecutionTracer
from errand_agent.core.llm.gemini_live import GeminiLiveLLM
from errand_agent.core.llm.scripted import ScriptedLLM

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def print_separator(char="=", length=75):
    print(char * length)

def display_side_by_side(chat_text: str, trace_events: list):
    print_separator("-")
    print(" [AGENT RESPONSE]")
    for line in chat_text.strip().split("\n"):
        print(f"   {line}")
    print()
    print(" [LIVE EXECUTION TRACE LOGS]")
    if not trace_events:
        print("   (No new telemetry events)")
    for ev in trace_events:
        etype = ev.event_type.upper()
        lat = f"[{ev.latency_ms:.1f}ms]" if ev.latency_ms else ""
        payload_str = json.dumps(ev.payload, default=str)
        if len(payload_str) > 90:
            payload_str = payload_str[:87] + "..."
        print(f"   >> {etype:18} {lat:9} {payload_str}")
    print_separator("-")

def run_cli():
    print_separator("=")
    print("        ERRAND AGENT - FOUNDING AI ENGINEER DEMO")
    print("  Safe, deterministic, code-governed errand booking agent")
    print_separator("=")
    print("Available demo shortcuts:")
    print("  • Type any regular message (e.g. 'Find a plumber in Indiranagar mornings only under 1500')")
    print("  • /demo happy      - Run automated full happy path booking")
    print("  • /demo injection  - Trigger provider review prompt injection")
    print("  • /demo timeout    - Trigger timeout-after-success recovery")
    print("  • /memory          - Inspect stated vs. inferred memory")
    print("  • /quit            - Exit demo")
    print_separator("=")

    # Check if Gemini key is available
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key and not api_key.startswith("your_"):
        llm = GeminiLiveLLM(api_key=api_key)
        print(">> LLM Mode: Live Gemini API (Online)")
    else:
        llm = ScriptedLLM()
        print(">> LLM Mode: Scripted Deterministic Engine (Offline)")

    service = MockProviderService(seed=42)
    tracer = ExecutionTracer(run_id="cli-interactive-session")
    agent = ErrandAgent(provider_service=service, tracer=tracer, llm=llm)

    last_event_count = 0

    while True:
        try:
            user_input = input("\nUser > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ["/quit", "exit", "quit"]:
                print("Session closed. Good luck!")
                break

            elif user_input.lower() == "/memory":
                mem = agent.memory.view_memory()
                print("\n[PERSISTED PREFERENCES MEMORY]")
                for item in mem:
                    print(f"  • {item['key']}: {item['value']} (Source: {item['source']}, Confirmed: {item['confirmed']})")
                continue

            elif user_input.lower() == "/demo happy":
                print("\n[Running Demo: Full Booking Happy Path]")
                steps = [
                    "Find a plumber for my kitchen tap this week in Indiranagar, mornings only, under 1500.",
                    "Yes, please book it."
                ]
                for s in steps:
                    print(f"\nUser > {s}")
                    time.sleep(0.5)
                    resp = agent.handle_message(s)
                    new_events = tracer.events[last_event_count:]
                    last_event_count = len(tracer.events)
                    display_side_by_side(resp, new_events)
                continue

            elif user_input.lower() == "/demo injection":
                print("\n[Running Demo: Prompt Injection Defense in Provider Review]")
                s = "Find a plumber in Indiranagar mornings only under 1500."
                print(f"\nUser > {s}")
                resp = agent.handle_message(s)
                new_events = tracer.events[last_event_count:]
                last_event_count = len(tracer.events)
                display_side_by_side(resp, new_events)
                print("\n>> Notice: The review contained 'SYSTEM OVERRIDE', but the agent quarantined it")
                print("   and safely prompted the user for explicit approval instead of auto-executing!")
                continue

            elif user_input.lower() == "/demo timeout":
                print("\n[Running Demo: Timeout-After-Success Recovery]")
                service.force_book_outcome = "timeout_and_booked"
                s1 = "Find an electrician in Koramangala mornings only under 1000."
                print(f"\nUser > {s1}")
                resp1 = agent.handle_message(s1)
                new_events1 = tracer.events[last_event_count:]
                last_event_count = len(tracer.events)
                display_side_by_side(resp1, new_events1)

                s2 = "Yes, please confirm and book."
                print(f"\nUser > {s2}")
                resp2 = agent.handle_message(s2)
                new_events2 = tracer.events[last_event_count:]
                last_event_count = len(tracer.events)
                display_side_by_side(resp2, new_events2)
                service.force_book_outcome = None
                continue

            # Standard chat turn
            resp = agent.handle_message(user_input)
            new_events = tracer.events[last_event_count:]
            last_event_count = len(tracer.events)
            display_side_by_side(resp, new_events)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting session...")
            break

if __name__ == "__main__":
    run_cli()
