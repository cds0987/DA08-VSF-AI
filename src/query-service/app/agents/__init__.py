"""MOSA multi-agent core cho query-service (Orchestrator-Workers).

Cấu phần (cắm-tháo qua registry + manifest agents.yaml):
- registry.py:    Registry[T] generic (decorator built-in + entry-point plugin)
- base.py:        AgentRole ABC + WorkerInput/WorkerOutput (hợp đồng I/O role-agent)
- plan_schema.py: Plan/Step (pydantic) — validate output orchestrator
- manifest.py:    load agents.yaml (fallback-safe về mode 'react')

Xem docs/nguyenworking/orchestrator-workers-spec.md.
"""
