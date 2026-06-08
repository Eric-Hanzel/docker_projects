# 成功部署耗时统计

统计范围：
- 批次：`batch-20260421_220942-1938292`
- 成功样本来源：`success.txt`
- 说明：当前结果文件只覆盖到 `task-019`，因此统计只包含已落账的成功任务
- 统计口径：按 `success.txt` 中的 6 个唯一 `task_id`，到 `/home/eric/APDv1/.codex/state/task_history.jsonl` 中匹配对应 `COMPLETED_SUCCESS` 记录，使用 `finished_at - started_at` 计算耗时

统计结果：
- 成功部署项目数：`6`
- 平均耗时：`2023` 秒，约 `33分43秒`
- 最大耗时：`2692` 秒，约 `44分52秒`
- 最大耗时任务：`task-003`
- 对应项目：`https://github.com/emikulic/darkstat`

明细：

| task_id | url | started_at | finished_at | duration_seconds | duration_human |
|---|---|---|---|---:|---|
| task-003 | https://github.com/emikulic/darkstat | 2026-04-21T23:51:15+08:00 | 2026-04-22T00:36:07+08:00 | 2692 | 44m 52s |
| task-004 | https://github.com/grafana/grafana | 2026-04-22T00:36:49+08:00 | 2026-04-22T01:21:10+08:00 | 2661 | 44m 21s |
| task-006 | https://github.com/openobserve/openobserve | 2026-04-22T01:41:55+08:00 | 2026-04-22T02:05:30+08:00 | 1415 | 23m 35s |
| task-007 | https://github.com/netdata/netdata | 2026-04-22T02:05:47+08:00 | 2026-04-22T02:26:58+08:00 | 1271 | 21m 11s |
| task-008 | https://github.com/hyperdxio/hyperdx | 2026-04-22T02:27:19+08:00 | 2026-04-22T02:56:17+08:00 | 1738 | 28m 58s |
| task-016 | https://github.com/nicolargo/glances | 2026-04-22T08:54:00+08:00 | 2026-04-22T09:33:26+08:00 | 2366 | 39m 26s |

简要观察：

1. 这一批已成功样本整体比上一批更快
- 6 个成功项目里，有 4 个落在 `21-29` 分钟区间
- 只有 `darkstat` 和 `grafana` 超过 `44` 分钟

2. 成功样本多集中在中轻量监控/可观测性项目
- `openobserve`、`netdata`、`hyperdx`、`glances` 都没有出现特别重的 final replay 成本

3. 当前统计偏保守
- 因为 `task-020+` 尚未写入结果文件
- 如果后续还有成功任务落账，这份统计需要重新计算
