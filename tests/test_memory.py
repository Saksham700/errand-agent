from errand_agent.core.memory import MemoryStore, MemorySource

def test_stated_vs_inferred_memory():
    mem = MemoryStore()
    mem.set_stated_fact("area", "Indiranagar")
    assert mem.get_usable_fact("area") == "Indiranagar"

    # Inferred fact is not usable until confirmed
    mem.set_inferred_fact("earliest_time", "10:00")
    assert mem.get_usable_fact("earliest_time") is None

    # Confirm inferred fact
    mem.confirm_inferred_fact("earliest_time")
    assert mem.get_usable_fact("earliest_time") == "10:00"

def test_forget_tombstoning():
    mem = MemoryStore()
    mem.set_stated_fact("area", "Indiranagar")
    assert mem.get_usable_fact("area") == "Indiranagar"

    mem.forget_fact("area")
    assert mem.get_usable_fact("area") is None

    # Cannot be resurrected by inference
    assert mem.set_inferred_fact("area", "Indiranagar") is None
    assert mem.get_usable_fact("area") is None
