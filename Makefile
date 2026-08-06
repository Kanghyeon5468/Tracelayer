.PHONY: verify-core demo test run-api

verify-core:
	cd services/api && python -m compileall app tests
	cd services/api && python -c "from app.config import Settings; from app.fleet import FraudInvestigationFleet; case = FraudInvestigationFleet(Settings()).investigate('tx-9001'); print(case.case_id, case.status, case.risk_score, case.priority)"

demo:
	cd services/api && python -c "from app.config import Settings; from app.fleet import FraudInvestigationFleet; case = FraudInvestigationFleet(Settings()).investigate('tx-9001'); print(case.model_dump_json(indent=2))"

test:
	cd services/api && python -m pytest

run-api:
	cd services/api && uvicorn app.main:app --reload --port 8080
