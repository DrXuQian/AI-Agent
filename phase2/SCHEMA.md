# Phase 2 Task Definition Schema

每个任务是 `phase2/tasks/<id>.yaml`:

```yaml
id: openclaw_email_triage_x20      # unique task id, becomes filename
agent: openclaw                     # openclaw | claude_code
category: triage                    # for grouping in report
description: "20-email triage"     # human-readable label

# Setup: run BEFORE each repeat (idempotent fresh state)
setup:
  - "rm -rf {workspace}"
  - "mkdir -p {workspace}/inbox"
  - "cp -r {bench}/phase2/fixtures/inbox-20/* {workspace}/inbox/"

# Teardown: run AFTER each repeat (cleanup)
teardown:
  - "rm -rf {workspace}"

# Prompt: user message sent to agent. {workspace} substituted at runtime.
prompt: |
  Read all email files in {workspace}/inbox/. Classify each as
  [ACTION_REQUIRED], [FYI], or [SPAM]. Output a markdown briefing.

# Timeout per run (sec)
timeout: 300

# Optional: validation predicate
# (run after task; if non-zero exit code, mark run as failed)
validate:
  - "test -f {workspace}/inbox/email1.txt"   # fixture preserved
```

## Runtime variables substituted
- `{bench}` → `/root/autodl-tmp/agent-bench`
- `{workspace}` → `phase2/workspaces/<task_id>-run<N>`
- `{run_id}` → integer 1..N

## Output per run
`phase2/runs/<task_id>__cache<on|off>__r<N>.json`:
```json
{
  "task_id": "openclaw_email_triage_x20",
  "agent": "openclaw",
  "cache_mode": "on",
  "run_id": 1,
  "start_epoch": 1778892663,
  "end_epoch": 1778892682,
  "wall_sec": 19,
  "exit_code": 0,
  "metrics": { ... pulled from Prometheus ... },
  "output_excerpt": "first 500 chars of stdout",
  "agent_meta": { ... usage tokens, tool calls, etc ... }
}
```
