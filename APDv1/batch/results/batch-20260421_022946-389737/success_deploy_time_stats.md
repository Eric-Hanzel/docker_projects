# 成功部署耗时统计

统计范围：
- 批次：`batch-20260421_022946-389737`
- 成功样本来源：`success.txt`
- 统计口径：按 `success.txt` 中的 13 个唯一 `task_id`，到 `/home/eric/APDv1/.codex/state/task_history.jsonl` 中匹配对应 `COMPLETED_SUCCESS` 记录，使用 `finished_at - started_at` 计算耗时

统计结果：
- 成功部署项目数：`13`
- 平均耗时：`2302` 秒，约 `38分22秒`
- 最大耗时：`3291` 秒，约 `54分51秒`
- 最大耗时任务：`task-016`
- 对应项目：`https://github.com/Cacti/cacti`

明细：

| task_id | url | started_at | finished_at | duration_seconds | duration_human |
|---|---|---|---|---:|---|
| task-001 | https://docs.octobercms.com/4.x/setup/installation.html#minimum-system-requirements | 2026-04-21T02:30:08+08:00 | 2026-04-21T03:15:46+08:00 | 2738 | 45m 38s |
| task-002 | https://github.com/uasoft-indonesia/badaso | 2026-04-21T03:16:22+08:00 | 2026-04-21T03:56:58+08:00 | 2436 | 40m 36s |
| task-004 | https://github.com/grokability/snipe-it | 2026-04-21T04:13:40+08:00 | 2026-04-21T04:45:48+08:00 | 1928 | 32m 8s |
| task-005 | https://github.com/mediacms-io/mediacms | 2026-04-21T04:46:57+08:00 | 2026-04-21T05:21:26+08:00 | 2069 | 34m 29s |
| task-007 | https://github.com/gitlabhq/gitlabhq | 2026-04-21T05:55:30+08:00 | 2026-04-21T06:46:37+08:00 | 3067 | 51m 7s |
| task-011 | https://github.com/harness/drone | 2026-04-21T09:47:57+08:00 | 2026-04-21T10:11:54+08:00 | 1437 | 23m 57s |
| task-012 | https://github.com/concourse/concourse | 2026-04-21T10:12:39+08:00 | 2026-04-21T10:36:28+08:00 | 1429 | 23m 49s |
| task-013 | https://github.com/theonedev/onedev | 2026-04-21T10:36:48+08:00 | 2026-04-21T11:03:51+08:00 | 1623 | 27m 3s |
| task-015 | https://github.com/apache/incubator-devlake | 2026-04-21T12:04:30+08:00 | 2026-04-21T12:47:06+08:00 | 2556 | 42m 36s |
| task-016 | https://github.com/Cacti/cacti | 2026-04-21T12:47:52+08:00 | 2026-04-21T13:42:43+08:00 | 3291 | 54m 51s |
| task-018 | https://github.com/observium/observium | 2026-04-21T14:43:42+08:00 | 2026-04-21T15:37:21+08:00 | 3219 | 53m 39s |
| task-021 | https://github.com/prometheus/prometheus | 2026-04-21T16:58:09+08:00 | 2026-04-21T17:30:21+08:00 | 1932 | 32m 12s |
| task-022 | https://github.com/VictoriaMetrics/VictoriaMetrics | 2026-04-21T17:30:39+08:00 | 2026-04-21T18:07:20+08:00 | 2201 | 36m 41s |
