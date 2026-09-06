"""One-off helper: reset circuit, resume match node, resume pipeline."""
from matchers.alibaba_result_cache import reset_circuit
from execution.repository import ExecutionRepository
from db.session import session_scope
from db.models import RunLog

reset_circuit()

repo = ExecutionRepository()
nodes = repo.list_nodes(run_id=2)
match_nodes = [n for n in nodes if n["stage"] == "match"]
n = match_nodes[0]
print(f"node_id={n['id']} status={n['status']} token={n['resume_token']}")

if n["status"] == "human_required":
    repo.resume_human(n["id"], reason="captcha solved by human", expected_resume_token=n["resume_token"])
    print("Node reset to pending")

with session_scope() as s:
    run = s.query(RunLog).filter_by(id=2).first()
    run.status = "running"
    s.commit()
    print("RunLog status -> running")

from pipeline.orchestrator import resume_pipeline
run_id = resume_pipeline(2)
print(f"Done! RunLog id = {run_id}")
