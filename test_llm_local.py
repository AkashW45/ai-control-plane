# test_llm_local.py
from services.llm import generate_runbook_from_text

result = generate_runbook_from_text("Release 1.0 to QA")

print(result)
