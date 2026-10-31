from evals.scenarios import run_all_scenarios

def test_all_18_eval_scenarios_pass():
    results = run_all_scenarios()
    failures = [f"{r.name}: {r.actual}" for r in results if not r.passed]
    assert len(failures) == 0, f"Failed scenarios:\n" + "\n".join(failures)
    assert len(results) >= 15
