# 失败项目分析

- 输入记录数: 125
- 数据来源: `batch/Manual/Summary-1/failure_projects.jsonl`
- 证据来源: `batch/runs/<batch>/task-*/last_message.txt`、`trace.txt`、`codex.log`，以及模糊匹配到的 `DP_LOGS/<project>/summary.md`、`errors.log`、`deploy.log`、`audit_result.json`
- 证据覆盖: 125 条记录全部至少匹配到一组日志或结果证据
- 分类方法: 基于日志证据的启发式归类。分类之间会重叠，尤其是同一任务同时出现网络失败、超时和 audit 失败时。下面的数量应作为排障优先级信号，不应当理解为严格互斥的根因统计。

## 终态统计

- `TIMED_OUT`: 55 / 125，44.0%
- `COMPLETED_FAILED`: 34 / 125，27.2%
- `ABORTED`: 30 / 125，24.0%
- `COMPLETED_CONDITIONAL_SUCCESS`: 6 / 125，4.8%

## 分类模型

这些失败不应该按一个平铺列表理解。更有工程价值的划分是三类:

1. **外部不可控或不可完全消除**: APDv1 可以检测、缓存、重试或分类，但不能让外部依赖一定稳定，也不能绕过真实的业务前置条件。
2. **工程实现可显著改善**: 包括 runner、audit、重试预算、preflight、缓存、状态写入、失败分类等问题。它们可以在 APDv1 工程层面持续优化，并减少可避免失败。
3. **真正技术难点**: 即使网络和 runner 都稳定，这些项目仍然难。需要更强的部署理解、平台专项路径、状态初始化和功能验收。

## 1. 外部不可控或不可完全消除

### 镜像、网络、依赖源不稳定

日志证据包括 Docker Hub / GHCR / Quay / GitHub release / npm / Maven / apt 失败: 镜像拉取慢、EOF、`429 Too Many Requests`、`403`、镜像层解压失败、依赖下载长时间无进展等。典型例子包括 Zabbix、SigNoz、OpenSearch Dashboards、OpenNMS、Thanos、Windmill。

这是最明显的失败面，但不是纯粹的部署逻辑 bug。APDv1 可以通过 cache-first、missing-only pull、有界重试、preflight、镜像保留和更清晰的失败分类来缓解；但当上游 tag 缺失、外部 registry 限流、网络路径持续不可用时，工程实现不能保证成功。

建议处理:

- 精确官方 tag 已在本地存在时，优先复用本地镜像。
- 官方文档允许时，用 `docker compose up --pull missing`，避免无条件刷新远端镜像。
- 任务结束后保留可复用基础镜像和服务镜像，避免全局 prune。
- 将 registry 硬失败与应用 bootstrap 失败分开记录。
- 长期批处理场景下，可增加常用基础镜像和服务镜像的可选预热。

### 外部 license、token、SaaS 注册和私有凭据

例子包括 FileRun license key、Rocket.Chat workspace registration、actions-runner-controller GitHub 凭据、Buildkite agent token。这些不是普通技术失败，也不应该通过 workaround 隐藏。

建议处理:

- 尽可能产出技术上完整且自洽的 bundle。
- 当剩余 blocker 是外部前置条件并且已经文档化时，使用 `COMPLETED_CONDITIONAL_SUCCESS`。
- 持久化 `conditional_reason` 和 `blocking_requirement`。
- 在 `README_QUICKSTART.md` 中明确哪些环境变量是 required，哪些是 optional。

### 输入目标本身不是完整可部署应用

部分目标是组织主页、库、框架、工具链、文档仓库或底层组件，而不是可直接部署的产品。例子包括组织级 URL，以及 pdf.js、poppler、tesseract、LibreOffice core、Travis CI org、Buildkite org 这类库/工具/组织目标。

建议处理:

- 记录 `selected_deploy_target=app|docs-only` 和 `target_selection_reason`。
- 如果存在官方 runnable app、demo、starter、image 或 chart，优先选择它们。
- 不要为了满足 bundle 形状而伪造弱部署。
- 如果确实没有可运行产品，应失败或条件成功，并明确说明目标选择原因。

## 2. 工程实现可显著改善

### 超时和预算耗尽

很多超时来自大镜像拉取、源码构建、Kubernetes 启动、前端构建、数据库初始化或首次 bootstrap。这一类一部分受外部环境影响，一部分受工程策略影响。

建议处理:

- 在昂贵操作前增加 lightweight preflight: Docker 可用性、磁盘空间、目标/release/tag 可达性、registry/package-source 可达性、高置信已知失败模式。
- 按阶段拆分重试预算: official flow 与 final portable bundle build 分开计算。
- 对仍在进展的慢 pull/build 保持 progress-aware waiting；只有明确失败或确认无进展时才重试。
- Kubernetes-heavy 或 large-source-build 项目应与小型 compose app 使用不同预算和预期。

### Runner/tool 层异常和状态写入问题

证据包括 interrupted sessions、`stdin is closed for this session`、重复 tool 字段、`ABORTED`、terminal state 没有干净写入等。这不是目标项目部署问题。

建议处理:

- 确保 terminal task state 在受保护的 completion path 中写入。
- 即使 `codex exec` 或工具调用失败，也保留最后有效日志。
- 避免生成无效工具参数，避免长运行 session 的错误用法。
- 将 runner-owned `TIMED_OUT` / `ABORTED` 与 agent-owned 部署失败明确区分。

### 交付物/audit 规则过严或规则漂移

部分失败不是应用没跑起来，而是 final bundle contract 与项目形态不匹配。旧规则对 image-first 或 no-DB 项目过于刚性，例如所有项目都要求 source snapshot 与 DB dump，或者把所有非 PASS 都当作普通失败。

当前/建议处理:

- 对不需要源码快照的 official image-first 项目，使用 `runtime-config-initialized.tar.gz`。
- 对没有初始化 DB 状态的项目，使用 `initdb/README_NO_DB.md`。
- 对有效外部 blocker 允许 `CONDITIONAL` audit verdict。
- 要求 `verification_result.json`，让 audit 读取结构化 final verification evidence。
- runtime artifact 修复必须回到 portable bundle worker；parent-only 修复只限 docs/report/metadata 问题。

### 资源和宿主环境容量

大镜像、大源码树、重型编译任务、大 volume 初始化、本地 Kubernetes 集群都会压磁盘、内存、CPU 和 Docker 网络。这部分有宿主环境因素，但 APDv1 可以更早发现。

建议处理:

- 重型任务开始前 preflight 磁盘和 Docker 状态。
- 将宿主资源不足证据与应用逻辑失败分开记录。
- 对 official image-first 项目，除非需要源码 patch 或本地构建，否则不要 clone 全源码。
- 保留可复用缓存，不要每个任务后都删除。

## 3. 真正技术难点

### Kubernetes / Helm / Operator / 集群型项目

例子包括 Argo CD、Argo Workflows、Flux、Flagger、Devtron、Spinnaker、Testkube、Rancher、Gloo、Brigade 等。这些不是简单的 `docker compose up` 应用。在验证产品前，必须先有一个可工作的集群层。

难点:

- 创建并管理本地 kind/k3s/minikube 生命周期。
- 安装 CRD、controller、webhook、RBAC、storage、ingress，以及可选 cert-manager。
- 等待 init job、migration、controller reconciliation 完成。
- 将 service/ingress 映射成稳定的本地 URL。
- 避免污染宿主 kube context。
- 将 chart、values、CRD、镜像和验证流程一起封装进 portable deliverable。

这一类需要专用 Kubernetes bundle 路径，而不是简单延长 compose 重试。

### 大型源码构建和复杂 toolchain

例子包括 OpenNMS、LibreOffice、Chromium/DevTools、Electron 项目、大型 Java monorepo、C/C++ 原生依赖栈、MinecraftForge 风格构建链。

难点:

- 精确 toolchain 版本。
- 系统依赖面很大。
- 编译时间长，内存/磁盘消耗高。
- 官方构建流程经常默认 CI 或 release maintainer 环境。
- 构建成功不等于存在可运行的 Web/operator 应用。

工程实现可以通过缓存、preflight 和目标选择减少浪费，但底层复杂度是真实存在的。

### 运行后验收失败

有些任务达到 container-up 或部分服务 ready，但真实外部可用性失败。Zadig 是明确例子: 直接 port-forward 到内部 portal 可访问，但 public gateway 返回 `502`，因此最终验收失败。

难点:

- 找到真实官方 user-facing entrypoint。
- 区分 container health 与 product readiness。
- 检查前端 asset、API/UI 边界、auth/bootstrap flow 和具体路由行为。
- 识别 HTTP 200 错误页、预期 UI 却返回 raw API JSON、framework exception page 等假阳性。

这是核心部署理解能力，必须保持严格验收。

### 多服务状态初始化和迁移

很多产品不只是启动容器，还需要 DB schema、seed data、admin user、object storage、search index、queue worker、scheduler、websocket service、license/bootstrap wizard 或生成的 runtime config。

难点:

- 判断哪些状态必须快照，哪些状态可以重建。
- 让 reset/deploy/verify 脚本足够幂等，能支撑迁移。
- 处理生成出来的 host/port/domain artifacts。
- 在不隐藏必要外部输入的前提下保持 bundle 可迁移。

## 实践优先级

收益最高的改进顺序是:

1. cache-first 镜像/依赖行为，以及安全的缓存保留。
2. 昂贵操作前的 lightweight preflight 和更清晰的 blocker 分类。
3. 更稳健的 runner terminal-state 与日志保留。
4. 对外部前置条件使用独立 conditional 路径。
5. 为 Kubernetes/Helm/operator 项目和大型源码构建项目设计专用路径。
6. 严格功能验收，检查真实 user/operator 行为，而不只是端口和容器健康。

## 当前分类信号

旧的平铺关键词分类仍可作为原始排障信号，但不应作为最终根因标签:

比例分母为全部 125 条失败记录。由于同一项目可以同时命中多个分类，下面比例会重叠，相加会超过 100%。

| 失败原因信号 | 命中数 | 占全部失败记录比例 |
| --- | ---: | ---: |
| 镜像/网络/依赖下载失败 | 119 | 95.2% |
| Kubernetes/集群/Helm依赖复杂 | 111 | 88.8% |
| 交付物/audit门失败 | 95 | 76.0% |
| 超时/预算耗尽 | 91 | 72.8% |
| 运行时启动/健康/HTTP验证失败 | 89 | 71.2% |
| 目标选择/上游不是完整可部署应用 | 65 | 52.0% |
| 源码构建/语言工具链失败 | 52 | 41.6% |
| 资源/磁盘/宿主限制 | 44 | 35.2% |
| 异常中止/未写终态 | 42 | 33.6% |
| 外部前置条件/license/token | 34 | 27.2% |

## 互斥主因比例

为了看清“每个项目主要卡在哪一步”，这里给每条失败记录只分配一个主因。归类规则是启发式的: `COMPLETED_CONDITIONAL_SUCCESS` 优先归为外部前置条件，`ABORTED` 优先归为异常中止/未写终态，`TIMED_OUT` 优先归为超时/预算耗尽；剩余 `COMPLETED_FAILED` 再按 evidence 文本和分类信号选择最具体的主因。因此这个表相加为 100%，但它比上面的重叠分类更粗。

| 主要导致失败原因 | 项目数 | 占全部失败记录比例 |
| --- | ---: | ---: |
| 超时/预算耗尽 | 55 | 44.0% |
| 异常中止/未写终态 | 30 | 24.0% |
| 镜像/网络/依赖下载失败 | 23 | 18.4% |
| 外部前置条件/license/token | 13 | 10.4% |
| Kubernetes/集群/Helm依赖复杂 | 3 | 2.4% |
| 资源/磁盘/宿主限制 | 1 | 0.8% |
| **合计** | **125** | **100.0%** |

## 高层归因拆分

如果把 `镜像/网络/依赖下载失败` 和 `超时/预算耗尽` 视为外部网络、依赖源、远端服务或长时间拉取/下载导致的失败，则这类主因合计为 78 / 125，占 62.4%。

真正按互斥主因落到项目复杂度本身的记录较少: `Kubernetes/集群/Helm依赖复杂` 加 `资源/磁盘/宿主限制` 合计为 4 / 125，占 3.2%。这里采用的是严格口径，只统计主因明确不是外部网络、runner 中止或 license/token 前置条件的项目复杂度失败。

剩余 43 / 125，占 34.4%，主要是 runner/tool 异常中止和外部 license/token/SaaS 注册等前置条件，不应归为项目复杂度。

| 高层归因 | 包含的互斥主因 | 项目数 | 占全部失败记录比例 |
| --- | --- | ---: | ---: |
| 外部网络/服务型失败 | 超时/预算耗尽；镜像/网络/依赖下载失败 | 78 | 62.4% |
| 项目复杂度型失败，严格口径 | Kubernetes/集群/Helm依赖复杂；资源/磁盘/宿主限制 | 4 | 3.2% |
| 其他非项目复杂度原因 | 异常中止/未写终态；外部前置条件/license/token | 43 | 34.4% |
| **合计** |  | **125** | **100.0%** |

## 项目索引

| Project | Status | Categories | Evidence paths | Short evidence |
| --- | --- | --- | --- | --- |
| `filerun` | `COMPLETED_CONDITIONAL_SUCCESS` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-006/last_message.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-006/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-006/codex.log` | blocker with `POST /index. |
| `zadig` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_022946-389737/task-006/last_message.txt`<br>`batch/runs/batch-20260421_022946-389737/task-006/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-006/codex.log` | FAILED`. |
| `gitlabhq` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-011/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-011/codex.log` | FAILED 5. |
| `argo-cd` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260518_220922-2229334/task-006/trace.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-006/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --text ingress --limit 5 2026-05-18T17:13:39. |
| `argo-workflows` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_022946-389737/task-010/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-010/codex.log` | failed; curl 56 GnuTLS recv error (-9): Error decoding the re. |
| `flagger` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_022946-389737/task-014/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-014/codex.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-04-21T03:10:50. |
| `zabbix` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260421_022946-389737/task-019/last_message.txt`<br>`batch/runs/batch-20260421_022946-389737/task-019/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-019/codex.log` | blocking issue was host-level Docker registry instability: official image pulls repeatedly failed with mirror `EOF`, `429 Too Many Requests`, and one `mysql:8. |
| `thanos` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260517_175023-53916/task-009/last_message.txt`<br>`batch/runs/batch-20260517_175023-53916/task-009/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-009/codex.log`<br>`DP_LOGS/thanos-0-34-0-final/summary.md` | failures: the direct Quay pull for `quay. |
| `opennms` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_022946-389737/task-024/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-024/codex.log` | failure output, so I’m leaving it alone per the patience rules. |
| `centreon` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260421_022946-389737/task-025/trace.txt`<br>`batch/runs/batch-20260421_022946-389737/task-025/codex.log` | blocker is network reliability against GitHub/Centreon. |
| `openitcockpit` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260421_220942-1938292/task-001/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-001/codex.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-04-21T14:16:30. |
| `monitorix` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260421_220942-1938292/task-002/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-002/codex.log` | failure evidence yet. |
| `signoz` | `COMPLETED_FAILED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_220942-1938292/task-005/last_message.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-005/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-005/codex.log` | blocker was the host’s Docker mirror path: `signoz`, `otel-collector`, and `clickhouse` images pulled, but `signoz/zookeeper:3. |
| `skywalking` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_220942-1938292/task-009/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-009/codex.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-04-21T18:58:01. |
| `metabase` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260421_220942-1938292/task-011/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-011/codex.log` | failed to parse function arguments: duplicate field `yield_time_ms` at line 1 column 136 2026-04-21T22:33:09. |
| `redash` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260421_220942-1938292/task-012/last_message.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-012/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-012/codex.log` | FAILED`. |
| `opensearch-dashboards` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260421_220942-1938292/task-014/last_message.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-014/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-014/codex.log` | FAILED`. |
| `mattermost` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260421_220942-1938292/task-019/last_message.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-019/trace.txt`<br>`batch/runs/batch-20260421_220942-1938292/task-019/codex.log`<br>`DP_LOGS/mattermost-11-7-2/summary.md` | FAILED`. |
| `garden` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-028/last_message.txt`<br>`batch/runs/batch-20260517_175023-53916/task-028/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-028/codex.log`<br>`DP_LOGS/garden-0-14-20/summary.md` | FAILED`. |
| `rocket-chat` | `COMPLETED_CONDITIONAL_SUCCESS` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260422_235849-141807/task-014/last_message.txt`<br>`batch/runs/batch-20260422_235849-141807/task-014/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-014/codex.log`<br>`DP_LOGS/rocketchat-final/summary.md` | blocker is now explicit and product-owned, not inferred: step 3 is `Register your workspace`, and it requires an external registration path with Rocket. |
| `discourse` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260422_235849-141807/task-015/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-015/codex.log` | timeout_ms=600000 2026-04-23T00:56:17. |
| `appwrite` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260422_235849-141807/task-020/last_message.txt`<br>`batch/runs/batch-20260422_235849-141807/task-020/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-020/codex.log` | failed before Appwrite reached a runnable state. |
| `tooljet` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260422_235849-141807/task-022/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-022/codex.log` | failure_avoidance_patterns ports-and-network --limit 3 2026-04-23T05:44:48. |
| `budibase` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260422_235849-141807/task-023/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-023/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 3 2026-04-23T06:45:51. |
| `outline` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260422_235849-141807/task-024/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-024/codex.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-04-23T07:45:00. |
| `flarum` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token | `batch/runs/batch-20260422_235849-141807/task-025/trace.txt`<br>`batch/runs/batch-20260422_235849-141807/task-025/codex.log`<br>`DP_LOGS/flarum-framework-final/summary.md`<br>`DP_LOGS/flarum-framework-final/audit_result.json` | failure_avoidance_patterns --subcategory dependency-gates --limit 3 2026-04-23T08:47:15. |
| `erpnext` | `COMPLETED_FAILED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-001/last_message.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-001/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-001/codex.log` | FAILED`, and that terminal state has been written. |
| `seafile` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-004/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-004/codex.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-04-23T18:16:35. |
| `cryptpad` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-008/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-008/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 3 2026-04-23T21:05:25. |
| `alfresco-community-repo` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-009/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-009/codex.log`<br>`DP_LOGS/alfresco-community-repo-gh-final/deploy.log` | failure_avoidance_patterns --subcategory dependency-gates --text java --limit 5 2026-04-28T21:36:21. |
| `agola` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-016/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-016/codex.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-04-24T00:49:05. |
| `devtron` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260423_234220-1934377/task-018/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-018/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 5 2026-04-24T02:28:22. |
| `flux2` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-019/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-019/codex.log` | failure_avoidance_patterns ports-and-network --limit 3 2026-04-24T03:32:31. |
| `gerrit` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260423_234220-1934377/task-020/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-020/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 5 2026-04-24T04:29:02. |
| `hyscale` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260423_234220-1934377/task-024/trace.txt`<br>`batch/runs/batch-20260423_234220-1934377/task-024/codex.log` | failure_avoidance_patterns --subcategory ports-and-network 2026-04-24T07:25:01. |
| `keploy` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-002/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-002/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 5 2026-04-24T12:34:39. |
| `openproject` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂 | `batch/runs/batch-20260424_194721-132027/task-003/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-003/codex.log` | failure_avoidance_patterns --subcategory verification --query 'http 200 false positive content checks assets web ui api' 2026-04-24T13:34:03. |
| `pipecd` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-004/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-004/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 5 2026-04-24T14:34:39. |
| `redmine` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-005/last_message.txt`<br>`batch/runs/batch-20260424_194721-132027/task-005/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-005/codex.log` | FAILED`. |
| `screwdriver` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-011/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-011/codex.log` | failure_avoidance_patterns --subcategory verification --limit 5 2026-05-17T14:27:00. |
| `spinnaker` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-007/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-007/codex.log` | failed to load image: command "docker exec --privileged -i spinnake. |
| `testkube` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-009/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-009/codex.log` | failed to parse function arguments: duplicate field `yield_time_ms` at line 1 column 1222 2026-04-24T18:53:31. |
| `github-com-travis-ci` | `COMPLETED_FAILED` | Kubernetes/集群/Helm依赖复杂<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-010/last_message.txt`<br>`batch/runs/batch-20260424_194721-132027/task-010/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-010/codex.log` | FAILED`. |
| `actions-runner-controller` | `COMPLETED_CONDITIONAL_SUCCESS` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-024/last_message.txt`<br>`batch/runs/batch-20260424_194721-132027/task-024/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-024/codex.log`<br>`DP_LOGS/actions-runner/summary.md` | failed exactly because no GitHub PAT or GitHub App credentials were available for `githubConfigSecret`. |
| `kraken` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260424_194721-132027/task-025/last_message.txt`<br>`batch/runs/batch-20260424_194721-132027/task-025/trace.txt`<br>`batch/runs/batch-20260424_194721-132027/task-025/codex.log`<br>`DP_LOGS/krakend-2.13.4-final/summary.md` | failed, so I stopped before Phase 6 bundle extraction as required. |
| `agent` | `COMPLETED_CONDITIONAL_SUCCESS` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260426_021920-1909602/task-002/last_message.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-002/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-002/codex.log`<br>`DP_LOGS/buildkite-agent/summary.md` | blocker is external: full registration and job polling require a real `BUILDKITE_AGENT_TOKEN` from the target Buildkite organization or cluster. |
| `bosun` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260426_021920-1909602/task-003/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-003/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 5 2026-04-25T19:03:09. |
| `sensu-go` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260426_021920-1909602/task-004/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-004/codex.log` | FAILED 5. |
| `ceph` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260426_021920-1909602/task-020/last_message.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-020/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-020/codex.log` | FAILED`. |
| `zenko` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token | `batch/runs/batch-20260426_021920-1909602/task-021/last_message.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-021/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-021/codex.log` | failed against `127. |
| `localstack` | `COMPLETED_CONDITIONAL_SUCCESS` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260426_021920-1909602/task-022/last_message.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-022/trace.txt`<br>`batch/runs/batch-20260426_021920-1909602/task-022/codex.log` | failed` because `LOCALSTACK_AUTH_TOKEN` was not provided. |
| `nuxeo` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-006/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-006/codex.log` | failure_avoidance_patterns verification --limit 3 2026-04-26T10:57:30. |
| `mayan-edms` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂 | `batch/runs/batch-20260426_160150-2594076/task-007/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-007/codex.log` | failure_avoidance_patterns --subcategory runtime-init --limit 5 2026-04-26T10:59:25. |
| `openmediavault` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-013/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-013/codex.log`<br>`DP_LOGS/openmediavault-8-2-13-gh-final/deploy.log` | blocker before first boot is the Debian base image download; once it lands, I’ll launch the VM container, wa. |
| `middleware` | `COMPLETED_FAILED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260518_220922-2229334/task-001/last_message.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-001/trace.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-001/codex.log` | FAILED`. |
| `xigmanas` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-010/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-010/codex.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-04-26T11:03:24. |
| `sourcehut` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-013/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-013/codex.log` | failure_avoidance_patterns --subcategory source-fetch --limit 3 2026-04-26T11:15:10. |
| `github-com-buildkite` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-014/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-014/codex.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-04-26T11:16:32. |
| `teamcity-docker-images` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-026/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-026/codex.log` | failure. |
| `rhodecode-vcsserver` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-018/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-018/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 3 2026-04-26T13:22:03. |
| `kallithea` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260426_160150-2594076/task-019/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-019/codex.log` | failure_avoidance_patterns verification --limit 3 2026-04-26T14:21:51. |
| `reviewboard` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-020/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-020/codex.log` | timeout=30). |
| `phorge` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-021/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-021/codex.log` | failure_avoidance_patterns ports-and-network 2026-04-26T16:22:35. |
| `artifactory-oss` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260426_160150-2594076/task-023/last_message.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-023/trace.txt`<br>`batch/runs/batch-20260426_160150-2594076/task-023/codex.log` | failure was upstream artifact acquisition: the official Artifactory image pull from `releases-docker. |
| `st2` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260427_130800-3224921/task-003/trace.txt`<br>`batch/runs/batch-20260427_130800-3224921/task-003/codex.log` | failure instead: Docker Hub returned `EOF` while resolving `stackstorm/st2notifier:3. |
| `gitlab-runner` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token | `batch/runs/batch-20260427_130800-3224921/task-004/trace.txt`<br>`batch/runs/batch-20260427_130800-3224921/task-004/codex.log` | failure evidence. |
| `runner` | `COMPLETED_CONDITIONAL_SUCCESS` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260427_130800-3224921/task-005/last_message.txt`<br>`batch/runs/batch-20260427_130800-3224921/task-005/trace.txt`<br>`batch/runs/batch-20260427_130800-3224921/task-005/codex.log`<br>`DP_LOGS/actions-runner/summary.md` | failure_avoidance_patterns ports-and-network --limit 3 2026-04-27T08:41:57. |
| `prestashop` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-003/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-003/codex.log`<br>`DP_LOGS/prestashop-9.1.0-final/summary.md`<br>`DP_LOGS/prestashop-9.1.0-final/errors.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 5 2026-04-27T13:43:14. |
| `leantime` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-004/last_message.txt`<br>`batch/runs/batch-20260427_202344-68004/task-004/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-004/codex.log`<br>`DP_LOGS/leantime-3.7.3-final/summary.md` | failure before Leantime became runnable. |
| `remoting` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-006/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-006/codex.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-04-27T15:46:15. |
| `zulip` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-007/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-007/codex.log` | failure_avoidance_patterns runtime-init ports-and-network verification --. |
| `misskey` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-010/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-010/codex.log` | failure_avoidance_patterns --subcategory verification --query "single page app api health false positive login asset veri. |
| `element-web` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-012/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-012/codex.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-04-27T21:27:19. |
| `zammad` | `TIMED_OUT` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-015/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-015/codex.log` | failure or th. |
| `community-skeleton` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-018/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-018/codex.log` | failure_avoidance_patterns'): print(kind) f. |
| `firepad` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-020/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-020/codex.log` | failure_avoidance_patterns --subcategory verification --tags node,http,frontend --limit 5 2026-04-28T02:30:01. |
| `nodebb` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260427_202344-68004/task-023/trace.txt`<br>`batch/runs/batch-20260427_202344-68004/task-023/codex.log` | failure now. |
| `bigbluebutton` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-002/last_message.txt`<br>`batch/runs/batch-20260429_031115-174215/task-002/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-002/codex.log` | FAILED`. |
| `botpress` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-006/last_message.txt`<br>`batch/runs/batch-20260429_031115-174215/task-006/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-006/codex.log` | FAILED`. |
| `documentserver` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-007/last_message.txt`<br>`batch/runs/batch-20260429_031115-174215/task-007/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-007/codex.log` | FAILED`. |
| `core` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-012/last_message.txt`<br>`batch/runs/batch-20260429_031115-174215/task-012/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-012/codex.log`<br>`DP_LOGS/nagios-core-4-5-12-final/summary.md` | FAILED`. |
| `pdf-js` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-018/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-018/codex.log` | failure_avoidance_patterns --subcategory verification --limit 5 2026-04-29T03:22:26. |
| `poppler` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-019/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-019/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --query cmake build library official docs 2026-04-29T04:23:26. |
| `mupdf` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260429_031115-174215/task-020/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-020/codex.log` | failure_avoidance_patterns 2026-04-29T05:23:23. |
| `tesseract` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260429_031115-174215/task-021/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-021/codex.log` | failure_avoidance_patterns --subcategory verification --limit 5 2026-04-29T06:23:40. |
| `ocrmypdf` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260429_031115-174215/task-022/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-022/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 5 2026-04-29T07:23:29. |
| `hexo` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260429_031115-174215/task-025/trace.txt`<br>`batch/runs/batch-20260429_031115-174215/task-025/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --text node --limit 3 2026-04-29T10:25:06. |
| `kratos` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-007/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-007/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --q docker compose port conflict reverse proxy public port 2026-04-29T22:03:19. |
| `gluu-server` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-009/last_message.txt`<br>`batch/runs/batch-20260430_020828-698620/task-009/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-009/codex.log` | FAILED`. |
| `keto` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-015/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-015/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 3 2026-04-30T03:43:05. |
| `permify` | `ABORTED` | 异常中止/未写终态<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-016/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-016/codex.log` | FAILED 5. |
| `core` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-017/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-017/codex.log`<br>`DP_LOGS/nagios-core-4-5-12-final/summary.md`<br>`DP_LOGS/nagios-core-4-5-12-final/errors.log` | FAILED 5. |
| `supertokens-core` | `ABORTED` | 异常中止/未写终态<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-018/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-018/codex.log` | FAILED 5. |
| `fusionauth-app` | `ABORTED` | 异常中止/未写终态<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-019/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-019/codex.log` | FAILED 5. |
| `logto` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-021/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-021/codex.log` | FAILED 5. |
| `openldap` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用 | `batch/runs/batch-20260518_220922-2229334/task-002/trace.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-002/codex.log`<br>`DP_LOGS/openldap-2-6-13-gh-final/deploy.log` | failure_avoidance_patterns --subcategory verification --limit 5 2026-05-18T14:18:07. |
| `freeipa` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-023/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-023/codex.log` | FAILED 5. |
| `389-ds-base` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-024/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-024/codex.log` | FAILED 5. |
| `spiffe` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>交付物/audit门失败 | `batch/runs/batch-20260430_020828-698620/task-025/trace.txt`<br>`batch/runs/batch-20260430_020828-698620/task-025/codex.log` | FAILED 5. |
| `tyk` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-003/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-003/codex.log` | failure_avoidance_patterns --subcategory verification --query 'avoid false positive http 200 api only when web ui expecte. |
| `erxes` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-006/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-006/codex.log` | failure fr. |
| `windmill` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-008/last_message.txt`<br>`batch/runs/batch-20260517_175023-53916/task-008/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-008/codex.log` | blocker was transport, not application bootstrap: Docker daemon pulls to `ghcr. |
| `vscode` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260502_235952-92126/task-013/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-013/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --limit 3 2026-05-02T22:40:41. |
| `intellij-community` | `COMPLETED_FAILED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-015/last_message.txt`<br>`batch/runs/batch-20260502_235952-92126/task-015/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-015/codex.log` | FAILED`. |
| `chrome-extensions-samples` | `COMPLETED_FAILED` | Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-016/last_message.txt`<br>`batch/runs/batch-20260502_235952-92126/task-016/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-016/codex.log` | FAILED`. |
| `addons-server` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260502_235952-92126/task-017/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-017/codex.log`<br>`DP_LOGS/addons-server-2026-04-30/deploy.log` | failure_avoidance_patterns --subcategory verification --limit 3 2026-05-03T00:41:58. |
| `minecraftforge` | `COMPLETED_FAILED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-019/last_message.txt`<br>`batch/runs/batch-20260502_235952-92126/task-019/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-019/codex.log` | failed during MCP/Vineflower setup and Forge compilation because the machine was underprovisioned for this repo: about `1. |
| `ajenti` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260502_235952-92126/task-023/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-023/codex.log` | failure_avoidance_patterns --subcategory dependency-gates --tag python --text web 2026-05-03T03:41:55. |
| `ispconfig3` | `COMPLETED_FAILED` | 超时/预算耗尽<br>Kubernetes/集群/Helm依赖复杂<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260502_235952-92126/task-024/last_message.txt`<br>`batch/runs/batch-20260502_235952-92126/task-024/trace.txt`<br>`batch/runs/batch-20260502_235952-92126/task-024/codex.log` | FAILED`. |
| `virtualmin-gpl` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>外部前置条件/license/token<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260517_175023-53916/task-012/last_message.txt`<br>`batch/runs/batch-20260517_175023-53916/task-012/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-012/codex.log` | FAILED`. |
| `phpmyadmin` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260503_192605-650552/task-001/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-001/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 3 2026-05-03T11:27:12. |
| `dashboard` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260503_192605-650552/task-004/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-004/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 5 2026-05-03T13:20:27. |
| `rancher` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>资源/磁盘/宿主限制 | `batch/runs/batch-20260503_192605-650552/task-006/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-006/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 5 2026-05-03T14:02:14. |
| `pfsense` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-010/last_message.txt`<br>`batch/runs/batch-20260517_175023-53916/task-010/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-010/codex.log` | FAILED`. |
| `core` | `COMPLETED_FAILED` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>外部前置条件/license/token<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260518_220922-2229334/task-005/last_message.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-005/trace.txt`<br>`batch/runs/batch-20260518_220922-2229334/task-005/codex.log`<br>`DP_LOGS/nagios-core-4-5-12-final/summary.md` | FAILED`. |
| `organizr` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260503_192605-650552/task-020/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-020/codex.log` | failure_avoidance_patterns --subcategory verification --limit 5 2026-05-03T17:19:36. |
| `cockpit` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260503_192605-650552/task-022/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-022/codex.log`<br>`DP_LOGS/cockpit-361-final/summary.md`<br>`DP_LOGS/cockpit-361-final/audit_result.json` | failure. |
| `druid` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>交付物/audit门失败 | `batch/runs/batch-20260503_192605-650552/task-023/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-023/codex.log` | failure_avoidance_patterns --subcategory verification --q web console http 200 content check asset 2026-05-03T18:40:45. |
| `console` | `ABORTED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败 | `batch/runs/batch-20260503_192605-650552/task-025/trace.txt`<br>`batch/runs/batch-20260503_192605-650552/task-025/codex.log` | failure_avoidance_patterns --subcategory ports-and-network --limit 3 2026-05-03T19:20:41. |
| `brigade` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>资源/磁盘/宿主限制<br>交付物/audit门失败 | `batch/runs/batch-20260517_175023-53916/task-019/trace.txt`<br>`batch/runs/batch-20260517_175023-53916/task-019/codex.log`<br>`DP_LOGS/brigade-2-6-0-gh-final/errors.log`<br>`DP_LOGS/brigade-2-6-0-gh-final/deploy.log` | failure_avoidance_patterns verification brigade portable bundle 2026-05-17T20:11:30. |
| `devspace` | `COMPLETED_FAILED` | 镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260505_020527-5358/task-007/last_message.txt`<br>`batch/runs/batch-20260505_020527-5358/task-007/trace.txt`<br>`batch/runs/batch-20260505_020527-5358/task-007/codex.log`<br>`DP_LOGS/devspace-6-3-21/summary.md` | FAILED`. |
| `appflowy-cloud` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260505_151609-529698/task-003/trace.txt`<br>`batch/runs/batch-20260505_151609-529698/task-003/codex.log`<br>`DP_LOGS/appflowy-cloud-0-9-64-final/summary.md`<br>`DP_LOGS/appflowy-cloud-0-9-64-final/errors.log` | failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open 2026-05-05T08:52:04. |
| `zitadel` | `TIMED_OUT` | 超时/预算耗尽<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>目标选择/上游不是完整可部署应用<br>交付物/audit门失败 | `batch/runs/batch-20260505_151609-529698/task-008/trace.txt`<br>`batch/runs/batch-20260505_151609-529698/task-008/codex.log`<br>`DP_LOGS/zitadel-4-13-1-final/summary.md`<br>`DP_LOGS/zitadel-4-13-1-final/errors.log` | failure. |
| `casdoor` | `COMPLETED_FAILED` | 超时/预算耗尽<br>异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>源码构建/语言工具链失败<br>外部前置条件/license/token<br>交付物/audit门失败 | `batch/runs/batch-20260505_151609-529698/task-009/last_message.txt`<br>`batch/runs/batch-20260505_151609-529698/task-009/trace.txt`<br>`batch/runs/batch-20260505_151609-529698/task-009/codex.log` | FAILED`. |
| `gloo` | `ABORTED` | 异常中止/未写终态<br>镜像/网络/依赖下载失败<br>Kubernetes/集群/Helm依赖复杂<br>运行时启动/健康/HTTP验证失败<br>交付物/audit门失败 | `batch/runs/batch-20260505_151609-529698/task-011/trace.txt`<br>`batch/runs/batch-20260505_151609-529698/task-011/codex.log` | FAILED 5. |
