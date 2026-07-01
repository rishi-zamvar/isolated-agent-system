"""Telemetry: lightweight bus emissions for pipeline / gate / deploy outcomes.

These feed the three metrics that were previously dark because their source
events were never emitted (metrics/compute.py §PLAT, §ORCH):
  PipelineRun(PASS|FAIL)   -> plat_pipeline_green
  ChallengeThread(BLOCK)   -> plat_gate_catch_rate
  DeployRecord(DEPLOYED)   -> orch_clean_deploy_rate (numerator)
  DeployRecord(ROLLBACK)   -> orch_clean_deploy_rate (rollback signal)
"""
