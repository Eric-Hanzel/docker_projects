# 超时失败任务分析

统计范围：
- 批次：`batch-20260421_220942-1938292`
- 来源文件：`failure.txt`
- 只分析状态为 `TIMED_OUT` 的任务
- 说明：本批次结果目录当前只落账到 `task-019`，未写入 `success.txt` / `failure.txt` 的后续任务不纳入本分析

分析方法：
- 读取 `failure.txt` 确认超时任务列表
- 关联 `.codex/state/task_history.jsonl` 取每个任务的起止时间
- 检查每个任务目录下的 `trace.txt`、`codex.log`
- 检查对应 `DP_LOGS/<project>/deploy.log`、`errors.log`、`audit_result.json`
- 依据“最后一个明确完成步骤”和“最后一个明确错误/阻塞信号”判断卡点与原因

本批次超时任务共 `5` 个：
- `task-001` `https://github.com/it-novum/openITCOCKPIT`
- `task-002` `https://github.com/mikaku/Monitorix`
- `task-009` `https://github.com/apache/skywalking`
- `task-010` `https://github.com/apache/superset`
- `task-011` `https://github.com/metabase/metabase`

## task-001 `it-novum/openITCOCKPIT`

超时区间：
- `started_at=2026-04-21T22:10:17+08:00`
- `finished_at=2026-04-21T22:59:51+08:00`

卡住步骤：
- `Phase 4` 官方 compose 首次启动后的长时间镜像拉取与源码补档并行阶段

直接证据：
- `DP_LOGS/openitcockpit/deploy.log` 末尾只记录到：
  - 已成功拉到部分镜像：`victoria-metrics`、`carbon-c-relay`、`carbon-cache`、`gearmand`、`redis`
  - 仍停留在 `stack remains in initial image acquisition; no containers created yet`
- `trace.txt` 显示父流程同时在补 `Deliverable/openitcockpit/source/`：
  - GitHub codeload tarball 被 `HTTP/2 stream cancel` 打断
  - ZIP 下载完成后又被判定为损坏
  - 最后回退到浅克隆，尚未完成

原因判断：
- 这不是应用启动后报出的业务错误
- 真正耗时点是“两条慢路径叠加”：
  - 官方 compose 镜像集很重，长时间还停在 pull 阶段
  - 源码快照多次传输失败，父流程持续切换获取手段
- 超时前始终没有进入容器创建，更没有进入 HTTP 验证

结论：
- 卡在 `Phase 4` 官方 compose 拉镜像 + 源码补档
- 根因是“镜像获取和 GitHub 源码快照都偏慢且反复中断，1 小时预算内未进入可验证运行态”

## task-002 `mikaku/Monitorix`

超时区间：
- `started_at=2026-04-21T23:00:21+08:00`
- `finished_at=2026-04-21T23:49:58+08:00`

卡住步骤：
- 主部署第 1 次验证失败后的第 2 次修复重建

先前已确认的问题：
- 第 1 次部署其实已经把镜像构建并跑起来，但运行态验证明确失败：
  - `Monitorix::httpd_setup: ERROR: invalid group defined.`
  - `Can't exec "ss": No such file or directory`
  - 外部访问只拿到 `HTTP/1.1 502 Bad Gateway`
- 父流程据此执行修复：
  - 安装 `iproute2`、`iptables`
  - 将 Monitorix 内置 HTTP 组从不兼容值改成 `nogroup`

直接证据：
- `DP_LOGS/monitorix/errors.log` 明确记录修复后重新 build
- 末尾停在 Ubuntu `apt-get install` 的长依赖安装阶段
- `trace.txt` 末尾多次轮询都没有新的业务层输出，只剩 package install 长时间推进

原因判断：
- 这不是单纯的“镜像拉取慢”
- 真实过程是：
  - 第 1 次部署暴露了容器内运行时依赖/组配置缺口
  - 修复方案本身需要重建镜像并重新安装大量 Ubuntu 包
  - 该重建在当前源速下耗时过长，超时前没有回到第二轮 HTTP 验证

结论：
- 卡在“修复后重建镜像”的第 2 次尝试
- 根因是“Monitorix 首次运行暴露容器依赖缺口，修复后的重建又被慢速 `apt` 安装拖过时限”

## task-009 `apache/skywalking`

超时区间：
- `started_at=2026-04-22T02:56:45+08:00`
- `finished_at=2026-04-22T05:41:10+08:00`

卡住步骤：
- `Phase 6` portable bundle 修复后的二次重放

执行到的程度：
- 主部署已经成功
- 主审计第 1 次因文档精度失败，第 2 次已 `PASS`
- `Phase 6` 第 1 次 bundle-only 重放其实已经完成并清理了 `source/`
- 但随后发现 bundle 脚本错误地覆盖了调用方端口变量，第一次验证其实打到了主部署端口 `18089`，不是隔离重放端口 `19089`

直接证据：
- `DP_LOGS/skywalking-final/deploy.log` 先出现一次：
  - `Phase 6 portable bundle success`
- 随后又追加修复记录：
  - `Remediation: preserve caller-supplied env port overrides in bundle scripts`
- 再次重放时 `errors.log` 出现：
  - `Bind for 0.0.0.0:17913 failed: port is already allocated`
  - 随后 `container skywalking_bundleverify-oap-1 exited (143)`

原因判断：
- 真正超时点不在主部署，而在 `Phase 6` 复验纠偏
- 第一轮 bundle 验证已基本成功，但因为端口覆盖 bug，证据不满足“隔离重放”要求
- 修复后第二轮又撞上 BanyanDB 端口冲突和 OAP 退出，父流程没来得及跑完新的完整验证和最终审计

结论：
- 卡在 `Phase 6` 纠偏后的再次重放
- 根因是“首次 portable 验证命中了错误端口，补救重放又遇到硬编码端口冲突，最终在 final audit 前超时”

## task-010 `apache/superset`

超时区间：
- `started_at=2026-04-22T05:42:15+08:00`
- `finished_at=2026-04-22T06:31:30+08:00`

卡住步骤：
- `Phase 6` 已完成后的最终收尾

执行到的程度：
- 主部署成功
- 主审计 `PASS`
- Phase 6 worker 多轮修复后最终成功
- final bundle audit 也已 `PASS`

直接证据：
- `DP_LOGS/superset-final/deploy.log` 末尾明确写到：
  - `retry attempt=7 success`
  - `post_verification_cleanup remove ./source`
- `DP_LOGS/superset-final/audit_result.json` 显示：
  - `"attempt": 1`
  - `"verdict": "PASS"`
- 但 `.codex/state/task_history.jsonl` 中该任务终态仍是：
  - `status=TIMED_OUT`
  - `primary_audit_verdict=PASS`
  - `audit_result_file=DP_LOGS/superset-final/audit_result.json`
  - `audit_verdict` 仍为空

原因判断：
- 这不是部署失败，也不是 final audit 未完成
- 实际上主部署、Phase 6、final audit 都已完成
- 真正缺失的是父流程在超时前没把 final audit 结果正式回写到任务状态并写出终态

结论：
- 卡在 `Phase 6` 通过后的状态落账
- 根因是“业务上已经成功，但父流程未在时限内完成 final audit 回写与终态写入”

## task-011 `metabase/metabase`

超时区间：
- `started_at=2026-04-22T06:31:47+08:00`
- `finished_at=2026-04-22T07:21:41+08:00`

卡住步骤：
- 主部署已验证成功，但还没进入 `Phase 5.5` 主审计

执行到的程度：
- 官方 `metabase/metabase:v0.60.1` 镜像最终拉取成功
- 应用已启动并完成初始化
- `verify_primary.sh` 已多次通过
- 管理员和普通用户都已通过 API 验证

直接证据：
- `DP_LOGS/metabase/summary.md` 已明确写成：
  - `Status: primary deployment running successfully`
- `DP_LOGS/metabase/deploy.log` 记录：
  - 官方镜像拉取完成后已切回真实成功路径
  - `/api/health`、登录页、静态资源、用户列表都验证成功
- `trace.txt` 末尾显示父流程迟迟没有进入审计，而是在持续等待并补 `Deliverable/metabase/source/`：
  - codeload 包持续增长
  - 后面又并行探测浅克隆作为更快来源

原因判断：
- 真正的业务部署已经成功
- 卡点是“流程错误地把 `Deliverable/metabase/source/` 当成主审计前的硬前置”
- 对 Metabase 这种官方镜像直跑即可完成部署、验证与后续交付的项目，源码快照本应是可选项，不应阻塞主审计
- 在当前网络下，持续补源码只消耗了剩余预算，并没有增加主部署是否成立的证据

结论：
- 卡在主部署成功后的错误契约补全
- 根因是“应用已可用，但流程仍把 source 视为硬前置，导致本可直接进入 `Phase 5.5` 的任务被补源码动作拖到超时”

## 汇总结论

按类型归类：

1. 主部署阶段的镜像/源码获取过慢
- `task-001` openITCOCKPIT

2. 首次运行暴露真实缺口，修复后重建又太慢
- `task-002` Monitorix

3. `Phase 6` 已接近或达到成功，但纠偏/收尾没在时限内完成
- `task-009` SkyWalking
- `task-010` Superset

4. 主部署已成功，但被错误的源码硬前置契约拖住，未进入主审计
- `task-011` Metabase

更核心的结论是：
- 这批 `TIMED_OUT` 不全是“应用没起来”
- `Superset`、`Metabase`、`SkyWalking` 都已经非常接近成功，其中 `Superset` 实际上已经完成全部核心验证
- 真正需要优先优化的是“收尾落账”和“把本可选的 source 快照误当成硬前置”的时间成本
