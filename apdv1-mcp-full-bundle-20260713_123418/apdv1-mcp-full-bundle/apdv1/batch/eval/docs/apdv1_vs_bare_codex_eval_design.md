# APDv1 local-run vs Bare Codex 小规模评测设计

## 目标

在同一组小规模、分类型项目数据集上，对比 APDv1 `local-run` 编排流程与裸 Codex baseline 的环境搭建效果。

这个评测要回答三个问题：

- APDv1 是否能在典型项目类型上提高环境搭建成功率？
- APDv1 是否比单段提示词 baseline 更能避免失败、识别失败或给出可解释结论？
- APDv1 为这些收益额外消耗了多少时间和 token？

## 数据集

数据集文件：

- `batch/eval/datasets/apdv1_vs_bare_codex_small.jsonl`

Agent-facing target 文件：

- `batch/eval/targets/apdv1_local_run_targets.jsonl`
- `batch/eval/targets/bare_codex_targets.jsonl`

评测元数据文件：

- `batch/eval/targets/eval_target_metadata.jsonl`

选择规则：

- 小规模实验：12 个项目。
- 每种类型最多 2 个项目。
- 只从下面两个文件中选择：
  - `batch/Manual/Summary-1/success_projects_targets.txt`
  - `batch/Manual/Summary-1/failure_projects_original.txt`
- 混合历史成功项目和历史失败项目。
- 避免让数据集被纯网络失败或纯 license/token 失败主导，因为这类样本不能很好衡量部署理解能力。
- `external_prerequisite` 当前采用“已提供 license key”的样本，用来测试两组是否能正确消费输入 extras 并完成部署，而不是只测试缺失前置条件时的条件成功分类。

Agent-facing target 只应包含实际环境搭建所需字段：

- `url`
- 必要 extras，例如 `license_key`
- APDv1 侧额外包含 `delivery_mode=local-run` 和 `portable_final_required=false`

不要把 `id`、`source_list`、`historical_status`、`category`、`expected_difficulty`、`selection_reason` 传给环境搭建 agent。这些字段只用于评测分组和结果分析，放在 `eval_target_metadata.jsonl` 中，避免给 agent 注入项目类型、历史成败和难度先验。

当前类型分布：

- `easy_image_first`: 2
- `db_backed_web_app`: 2
- `multi_service_business_app`: 2
- `kubernetes_helm_operator`: 2
- `observability_stack`: 2
- `ambiguous_or_library_target`: 1
- `external_prerequisite`: 1

## 对照组

### A 组：APDv1 `local-run`

使用 APDv1 规则，但本实验必须显式指定：

```text
delivery_mode=local-run
portable_final_required=false
```

不要直接原样使用当前 `batch/run_codex_batch.sh` 跑主实验，因为现有 batch runner 会按 APDv1 规则强制 `delivery_mode=portable-deliverable`。主实验需要 eval 专用 runner、参数覆盖，或单任务 `codex exec` prompt 明确设置 `delivery_mode=local-run`。

预期行为：

- 使用 APDv1 的 `AGENTS.md`、official deployment flow、经验系统、状态协议、`local-run` 模式、轻量 primary deployment audit、project-scoped cleanup 和缓存策略。
- 执行官方部署流，修复 live deployment，验证本机用户/运维入口和至少一个 baseline function。
- 通过 `primary_deploy_auditor` 轻量审计后结束。
- 不构建 `Deliverable/<project_name>-final/`。
- 不运行 `post-deploy-portable-bundle`。
- 不运行 `portable-bundle-audit`。
- 产出 APDv1 标准日志和状态记录。

### B 组：Bare Codex

使用 `codex exec` 加一段紧凑 baseline prompt。

裸 Codex prompt 应该公平，但不能等价于 APDv1：

- 可以要求 Codex 使用官方文档。
- 可以要求搭建本地可运行环境并做验证。
- 不应包含 APDv1 skills、audit contract、state protocol、portable bundle contract、experience store 或 Docker cleanup/cache policy。

推荐 baseline 目标：

> Build and verify a local runnable environment for the given project using official documentation where available. Prefer the simplest official Docker or compose path when available. Verify the main user-facing or operator-facing entrypoint and one baseline function. Record what was done, URLs, credentials, verification commands, and blockers.

## 执行 Runner

使用统一 eval runner：

```bash
bash batch/eval/run_eval_arm.sh apdv1_local_run
bash batch/eval/run_eval_arm.sh bare_codex
```

建议先做单任务 smoke：

```bash
TASK_LIMIT=1 TIMEOUT_MINUTES=60 bash batch/eval/run_eval_arm.sh bare_codex
TASK_LIMIT=1 TIMEOUT_MINUTES=60 bash batch/eval/run_eval_arm.sh apdv1_local_run
```

完整运行：

```bash
TIMEOUT_MINUTES=60 bash batch/eval/run_eval_arm.sh bare_codex
TIMEOUT_MINUTES=60 bash batch/eval/run_eval_arm.sh apdv1_local_run
```

runner 负责：

- 外层超时终止
- task 级日志目录
- `last_message.txt`
- `trajectory.jsonl`
- token usage 提取
- raw result JSONL
- Docker label 清理
- Docker 任务前后快照差分清理

Bare Codex 运行目录在 `/tmp/apdv1-bare-codex-eval/...`，避免自动继承 APDv1 仓库内的 `AGENTS.md`。日志和结果仍保存到 `batch/eval/runs/` 与 `batch/eval/results/`。

## 判定 Runner

部署 runner 只产出 raw result，不直接判定 `runtime_success`。原因是 exit code、APDv1 terminal state、assistant 最终话术都可能产生假阳性；最终成功率必须由独立 judge 基于证据判定。

对每个 raw result 运行：

```bash
bash batch/eval/run_judge_results.sh batch/eval/results/<run_id>/<arm>_raw_results.jsonl
```

输出：

- `<arm>_raw_results_judged.jsonl`
- `<arm>_raw_results_judged_summary.json`
- `judge-*/` 下的 judge prompt、context、log 和 last message

judge 使用统一 rubric：

- 必须看到合理部署目标、宿主机可访问入口、至少一个 baseline function 的证据。
- 不能只因为 `exit_code=0`、`RUNNER_COMPLETED`、`COMPLETED_SUCCESS` 或“容器运行中”就判成功。
- 可以使用 APDv1 audit evidence，但仍要检查 audit 中是否记录了具体 runtime/function 证据。
- 对裸 Codex 同样按 evidence 判断，不因为没有 APDv1 状态协议而扣分。

跨 arm 汇总：

```bash
python3 batch/eval/scripts/compare_judged_results.py \
  batch/eval/results/apdv1_vs_bare_codex_compare.json \
  batch/eval/results/<bare_run_id>/bare_codex_raw_results_judged.jsonl \
  batch/eval/results/<apdv1_run_id>/apdv1_local_run_raw_results_judged.jsonl
```

正式报告应使用 judged JSONL 和 compare JSON，而不是 raw JSONL。

## 成功标准

使用分层成功标准。主实验比较的是 APDv1 `local-run` 与裸 Codex 的本地可运行环境搭建能力，不比较 portable bundle 交付能力。

### 主成功：`runtime_success`

当以下条件全部满足时，记录 `runtime_success=true`：

1. 选择的部署目标对上游项目来说是合理的。
2. 必要服务成功启动。
3. 官方文档或项目预期的用户/运维入口可以从宿主机访问。
4. 验证不只是检查端口：
   - Web app：检查 UI HTML shell，加至少一个关键 JS/CSS asset；如适用，再检查登录、安装或 admin flow。
   - API/service：检查官方 health 或 readiness，再检查一个有意义的 API/CLI 操作。
   - storage/tooling：检查 create/list/read 或等价 baseline 操作。
   - Kubernetes/operator：检查相关 pod/controller ready，再检查一个产品特定命令、UI 或 API 行为。
5. 没有明显 framework error body、HTTP 5xx、预期 UI 却返回 raw API JSON、placeholder-only deployment 等假阳性。
6. 日志或 summary 中有证据记录。

### 条件成功：`conditional_success`

当以下条件全部满足时，记录 `conditional_success=true`：

1. 技术搭建路径是自洽的，并且已经做到当前条件下尽可能完整。
2. 完整业务初始化被外部前置条件阻塞。
3. blocker 不是 runner 自身造成的。
4. 缺失的输入或动作被清楚记录。

例子：

- 需要 license key
- 需要 GitHub token / PAT
- 需要 SaaS workspace registration
- 需要私有 registry 凭据

最终报告同时给出两个成功率：

- strict success rate: `runtime_success / total`
- useful completion rate: `(runtime_success + conditional_success) / total`

### 失败标签

每次失败记录一个 primary failure label，可选多个 secondary labels：

- `external_network_or_registry`
- `external_prerequisite`
- `target_not_runnable`
- `runner_or_tool_interrupt`
- `timeout_no_clear_failure`
- `resource_limit`
- `dependency_or_toolchain_build`
- `kubernetes_platform_complexity`
- `runtime_started_but_not_usable`
- `verification_or_evidence_missing`

## 指标

### 1. 成功率

每次运行需要记录：

- `runtime_success`: true/false
- `conditional_success`: true/false
- `terminal_status`: runner/agent status，如可用
- `failure_primary_label`: string 或 null
- `failure_secondary_labels`: array

### 2. 效率

记录四个时间指标：

- `wall_time_seconds`: 从 runner 开始到终态结束的完整耗时。这是主时间指标，因为它代表真实用户等待时间。
- `external_wait_seconds`: 明确由外部下载、registry 或 package source 等待主导的时间。
- `network_adjusted_seconds`: 只扣除明确外部等待后的近似对比指标。
- `blocked_wait_seconds`: 等待项目或平台自身 ready 的时间。它只用于解释复杂度，不从主效率指标中扣除。

首次小规模实验中：

```text
network_adjusted_seconds = wall_time_seconds - external_wait_seconds
```

只有日志明确显示以下情况时，才计入 `external_wait_seconds`：

- `docker pull`、`docker compose pull` 或 image layer download progress
- npm/pip/maven/apt/composer 等 package manager 的网络下载等待
- GitHub release/archive 下载
- 明确的 registry retry/backoff wait
- 针对外部源的 rate limit、EOF、403/429 retry wait

`blocked_wait_seconds` 记录项目复杂度等待，例如：

- app first-run bootstrap
- DB migration
- Kubernetes pod/controller reconciliation
- frontend build CPU time
- source compilation CPU time
- 因应用未 ready 导致的 healthcheck 或 verification retry

不要从主效率对比里扣除 `blocked_wait_seconds`。这些等待属于环境搭建复杂度，即使表面看起来像 idle waiting。

报告排序建议：

1. `runtime_success`
2. `conditional_success`
3. `wall_time_seconds`
4. `network_adjusted_seconds`
5. `total_tokens`

### 3. Token 开销

记录：

- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `reasoning_output_tokens`
- `total_tokens`

优先提取来源：

- `trajectory.jsonl` 中 `payload.type == "token_count"` 的 `event_msg`
- 取该任务最后一条 `token_count` 事件

如果一次运行包含 parent 和 subagent trajectories，记录：

- `parent_total_tokens`
- `subagent_total_tokens`
- `combined_total_tokens`

首次实验中，`combined_total_tokens` 作为 headline token cost。

## 公平性控制

两组尽量使用相同条件：

- 相同目标：本地可运行环境，而不是 portable final bundle
- 同一台机器
- 同一个 Docker daemon
- 同一个 workspace root
- 每个项目相同 time budget
- 相同 cache state policy

小规模实验缓存建议：

1. 不执行破坏性的全局 Docker prune。
2. 记录主要镜像是 cache hit 还是 network pull。
3. 可行时记录 `cache_condition`：`cold`、`warm`、`mixed` 或 `unknown`。

这不能完全消除网络波动，但可以让网络和缓存影响显性化，避免把实验变成 registry benchmark。

## 最小结果记录

每个项目、每个 arm 写一行 JSONL：

```json
{
  "run_id": "",
  "arm": "apdv1|bare_codex",
  "project_id": "",
  "url": "",
  "category": "",
  "runtime_success": false,
  "conditional_success": false,
  "terminal_status": "",
  "failure_primary_label": null,
  "failure_secondary_labels": [],
  "started_at": "",
  "ended_at": "",
  "wall_time_seconds": null,
  "external_wait_seconds": null,
  "external_wait_evidence": [],
  "network_adjusted_seconds": null,
  "blocked_wait_seconds": null,
  "blocked_wait_evidence": [],
  "cache_condition": "cold|warm|mixed|unknown",
  "input_tokens": null,
  "cached_input_tokens": null,
  "output_tokens": null,
  "reasoning_output_tokens": null,
  "total_tokens": null,
  "evidence_paths": [],
  "notes": ""
}
```
