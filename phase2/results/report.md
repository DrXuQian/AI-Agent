# Phase 2 Benchmark Report

Generated from `84` total runs across `28` (task, cache) groups.

## Per-task summary

Time per task (wall clock, mean ± std across runs):

| Task | Agent | Cache | n | OK | Wall sec (mean) | Wall sec (std) | TTFT p50 | Prefill TPS | Cache hit |
|---|---|---|---|---|---|---|---|---|---|
| `cc_01_code_understand` | claude_code | off | 3 | 3 | 18.21 | 3.0372 | 1.8125 | 4892.5214 | None |
| `cc_01_code_understand` | claude_code | on | 3 | 3 | 13.5133 | 2.1893 | 0.1752 | 5705.6914 | 0.902 |
| `cc_02_small_modify` | claude_code | off | 3 | 3 | 13.98 | 0.8118 | 1.75 | 6549.8459 | None |
| `cc_02_small_modify` | claude_code | on | 3 | 3 | 10.15 | 0.6324 | 0.1593 | 9240.505 | 0.9418 |
| `cc_03_bug_fix` | claude_code | off | 3 | 3 | 19.4967 | 5.1633 | 1.75 | 9686.2082 | None |
| `cc_03_bug_fix` | claude_code | on | 3 | 3 | 10.2 | 0.7351 | 0.1775 | 12211.6499 | 0.936 |
| `cc_04_refactor_sync_async` | claude_code | off | 3 | 2 | 153.9667 | 143.7134 | 1.7857 | 6217.2497 | None |
| `cc_04_refactor_sync_async` | claude_code | on | 3 | 3 | 52.9633 | 31.9334 | 0.1757 | 12385.3333 | 0.9606 |
| `cc_05_cli_tool` | claude_code | off | 3 | 3 | 98.0767 | 44.4903 | 1.75 | 8939.6674 | None |
| `cc_05_cli_tool` | claude_code | on | 3 | 3 | 60.5067 | 11.3559 | 0.1712 | 14006.3108 | 0.9766 |
| `cc_06_flask_crud` | claude_code | off | 3 | 2 | 179.6567 | 138.3189 | 1.8125 | 5189.603 | None |
| `cc_06_flask_crud` | claude_code | on | 3 | 3 | 41.24 | 19.4532 | 0.1705 | 8032.9586 | 0.9705 |
| `cc_07_textual_tui` | claude_code | off | 3 | 2 | 380.99 | 449.6622 | 1.7898 | 6061.3607 | None |
| `cc_07_textual_tui` | claude_code | on | 3 | 3 | 77.33 | 48.0784 | 0.1717 | 9897.0197 | 0.9723 |
| `cc_08_react_todo` | claude_code | off | 3 | 3 | 29.39 | 5.0325 | 1.75 | 2762.5054 | None |
| `cc_08_react_todo` | claude_code | on | 3 | 3 | 23.6233 | 2.5187 | 0.165 | 4074.6834 | 0.9715 |
| `oc_01_daily_briefing` | openclaw | off | 3 | 3 | 21.0533 | 2.105 | 0.6663 | 3701.8902 | None |
| `oc_01_daily_briefing` | openclaw | on | 3 | 3 | 20.5533 | 3.3382 | 0.1633 | 6886.2802 | 0.9104 |
| `oc_02_email_triage_x20` | openclaw | off | 3 | 3 | 22.3967 | 3.2343 | 0.7222 | 2937.2689 | None |
| `oc_02_email_triage_x20` | openclaw | on | 3 | 3 | 18.2367 | 2.4116 | 0.175 | 2905.3155 | 0.9166 |
| `oc_03_web_research` | openclaw | off | 3 | 3 | 19.75 | 0.4851 | 0.625 | 2170.9548 | None |
| `oc_03_web_research` | openclaw | on | 3 | 3 | 17.7867 | 2.4047 | 0.175 | 2202.9603 | 0.9262 |
| `oc_04_cron_heartbeat` | openclaw | off | 3 | 3 | 8.24 | 1.2537 | 0.625 | 1626.8162 | None |
| `oc_04_cron_heartbeat` | openclaw | on | 3 | 3 | 9.0167 | 0.9212 | 0.1687 | 2106.4543 | 0.9492 |
| `oc_05_multi_skill` | openclaw | off | 3 | 3 | 11.95 | 0.4716 | 0.625 | 2239.1796 | None |
| `oc_05_multi_skill` | openclaw | on | 3 | 3 | 9.7667 | 0.491 | 0.1667 | 2573.1047 | 0.946 |
| `oc_06_custom_skill_app` | openclaw | off | 3 | 3 | 107.8133 | 73.2896 | 1.4833 | 6198.4448 | None |
| `oc_06_custom_skill_app` | openclaw | on | 3 | 3 | 54.7333 | 7.7165 | 0.1714 | 4338.5013 | 0.9296 |

## Cache ON vs OFF

Same task, comparing cache modes (positive = cache helps):

| Task | Wall sec (ON) | Wall sec (OFF) | Δ wall | TTFT p50 (ON) | TTFT p50 (OFF) | Δ TTFT |
|---|---|---|---|---|---|---|
| `cc_01_code_understand` | 13.5133 | 18.21 | +4.70 | 0.1752 | 1.8125 | +1.64 |
| `cc_02_small_modify` | 10.15 | 13.98 | +3.83 | 0.1593 | 1.75 | +1.59 |
| `cc_03_bug_fix` | 10.2 | 19.4967 | +9.30 | 0.1775 | 1.75 | +1.57 |
| `cc_04_refactor_sync_async` | 52.9633 | 153.9667 | +101.00 | 0.1757 | 1.7857 | +1.61 |
| `cc_05_cli_tool` | 60.5067 | 98.0767 | +37.57 | 0.1712 | 1.75 | +1.58 |
| `cc_06_flask_crud` | 41.24 | 179.6567 | +138.42 | 0.1705 | 1.8125 | +1.64 |
| `cc_07_textual_tui` | 77.33 | 380.99 | +303.66 | 0.1717 | 1.7898 | +1.62 |
| `cc_08_react_todo` | 23.6233 | 29.39 | +5.77 | 0.165 | 1.75 | +1.58 |
| `oc_01_daily_briefing` | 20.5533 | 21.0533 | +0.50 | 0.1633 | 0.6663 | +0.50 |
| `oc_02_email_triage_x20` | 18.2367 | 22.3967 | +4.16 | 0.175 | 0.7222 | +0.55 |
| `oc_03_web_research` | 17.7867 | 19.75 | +1.96 | 0.175 | 0.625 | +0.45 |
| `oc_04_cron_heartbeat` | 9.0167 | 8.24 | -0.78 | 0.1687 | 0.625 | +0.46 |
| `oc_05_multi_skill` | 9.7667 | 11.95 | +2.18 | 0.1667 | 0.625 | +0.46 |
| `oc_06_custom_skill_app` | 54.7333 | 107.8133 | +53.08 | 0.1714 | 1.4833 | +1.31 |

## Agent profile: OpenClaw vs Claude Code

### claude_code (8 task types, cache=on)

- Mean wall time (s):     36.19 ± 25.68
- Mean prefill TPS:       9444.27 ± 3426.12
- Mean decode TPS:        98.98 ± 27.16
- Mean cache hit rate:    0.95 ± 0.03

### openclaw (6 task types, cache=on)

- Mean wall time (s):     21.68 ± 16.87
- Mean prefill TPS:       3502.10 ± 1844.29
- Mean decode TPS:        74.28 ± 41.88
- Mean cache hit rate:    0.93 ± 0.02
