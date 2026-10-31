import os
import sys
from evals.scenarios import run_all_scenarios, generate_markdown_report

def main():
    print("==================================================")
    print(" Running Errand Agent Automated Evaluation Suite")
    print("==================================================")
    results = run_all_scenarios()
    
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    
    for r in results:
        status_symbol = "PASS" if r.passed else "FAIL"
        print(f"[{status_symbol}] {r.name}: {r.actual} ({r.notes})")

    report_content = generate_markdown_report(results)
    output_path = "EVAL_REPORT.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nSuccessfully generated automated eval report: {output_path}")
    print(f"Summary: {passed_count}/{total_count} scenarios passed.")

    if passed_count < total_count:
        sys.exit(1)

if __name__ == "__main__":
    main()
