import pytest
from errand_agent.core.workflow import WorkflowManager

def test_workflow_missing_fields_and_prompt():
    wm = WorkflowManager(user_id="u1")
    missing = wm.get_missing_fields()
    assert "service" in missing
    assert "area" in missing
    assert "time_window" in missing

    prompt = wm.generate_missing_fields_prompt()
    assert "service" in prompt
    assert "area" in prompt

    # Update service
    wm.update_facts(service="plumber")
    missing2 = wm.get_missing_fields()
    assert "service" not in missing2
    assert "area" in missing2

    # Single detail correction preserves known facts
    wm.update_facts(area="Indiranagar", time_window="mornings only", budget=1500)
    assert wm.is_ready_for_search()
    
    # Correct only budget
    wm.update_facts(budget=1800)
    assert wm.state.service == "plumber"
    assert wm.state.area == "Indiranagar"
    assert wm.state.time_window == "mornings only"
    assert wm.state.budget == 1800
