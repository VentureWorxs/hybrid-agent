# SKILL: Hybrid Orchestrator

This skill guides Claude Code to make intelligent routing decisions using the hybrid-agent system.

## When to use this skill

Apply this skill when:
- Deciding whether to delegate a task to Ollama (local) or handle it yourself (Claude API)
- Working with content that may be sensitive, confidential, or PHI
- Tracking cost and routing decisions in the audit log
- Checking or comparing KPI metrics for the hybrid system

## Routing Decision Framework

### Route to Ollama (`ollama_summarize`, `ollama_analyze_code`, `ollama_infer`) when:
- Task complexity is LOW (summarization, classification, doc generation, repetitive inference)
- Content is SENSITIVE and must not leave this machine:
  - Code containing business logic or unreleased IP
  - Files in directories marked as private or confidential
  - Any content the user has flagged as sensitive
  - PHI data for the Propel tenant — **always local, no exceptions**
- High-volume batch tasks where API cost accumulates

### Route to Claude (yourself) when:
- Task requires multi-step reasoning or cross-file architectural decisions
- Final synthesis of outputs from multiple Ollama runs
- Novel problems not well-handled by Qwen3

## Operating Mode Awareness

Before starting work, check the active operating mode:
- `baseline` — all tasks route to Claude; use for cost benchmarking
- `hybrid` — normal routing (default)
- `shadow` — parallel runs for A/B validation; don't suppress either result

## Audit Logging

Log significant actions using `audit_log_event`:
```
Use audit_log_event to record: task_started, routing_decision, agent_invoked, task_completed
Set sensitivity_level appropriately (public / internal / confidential / sensitive_phi)
For PHI: always set agent_routed_to='ollama-local' and boundary_enforced=1
```

## Decision Cache

Before routing, check the cache:
```
Use get_decision with the task context to check for a cached routing decision.
If found, reuse it (avoids redundant audit events and approval prompts).
After making a new decision, use cache_decision to persist it for future sessions.
```

## KPI Scorecard

To check current performance mid-session:
```
Use get_scorecard with tenant_id and epoch='CURRENT'
Ask: "How are we doing on cost savings this month?"
```

## Example Routing Prompts

```
For this task, use ollama_analyze_code because the code is proprietary.
This content contains patient data — route to ollama_infer only.
Summarize all files in ./docs/ locally using ollama_summarize to keep costs low.
```
