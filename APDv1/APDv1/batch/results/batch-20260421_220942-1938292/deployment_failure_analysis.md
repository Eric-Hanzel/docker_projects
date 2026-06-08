# 部署失败项目分析

统计范围：
- 批次：`batch-20260421_220942-1938292`
- 来源文件：`failure.txt`
- 只分析明确终态为 `COMPLETED_FAILED` 的任务
- 说明：当前结果目录只覆盖到 `task-019`

分析方法：
- 读取 `failure.txt` 提取非超时失败任务
- 关联任务目录下的 `last_message.txt`、`trace.txt`、`codex.log`
- 检查对应 `DP_LOGS/<project>/deploy.log`、`errors.log`、`summary.md`
- 依据最终停留步骤和最后明确错误信号判断失败原因

本批次部署失败项目共 `7` 个：
- `task-005` `https://github.com/SigNoz/signoz`
- `task-012` `https://github.com/getredash/redash`
- `task-013` `https://github.com/elastic/kibana`
- `task-014` `https://github.com/opensearch-project/OpenSearch-Dashboards`
- `task-015` `https://github.com/Graylog2/graylog2-server`
- `task-018` `https://github.com/gitlabhq/gitlabhq`
- `task-019` `https://github.com/mattermost/mattermost`

## task-005 `SigNoz/signoz`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- `Phase 4` 官方 standalone Docker compose 拉镜像阶段

执行到的程度：
- 已按官方 `deploy/README.md` 路径进入 `deploy/docker`
- 已成功拉下：
  - `signoz/signoz:v0.119.0`
  - `signoz/signoz-otel-collector:v0.144.2`
  - `clickhouse/clickhouse-server:25.5.6`
- 本地也仅做了 host port 覆盖，不涉及服务拓扑改造

直接失败信号：
- `signoz/zookeeper:3.7.1` 一直是阻塞镜像
- `summary.md` / `errors.log` 记录的进度长期停在：
  - `~17.83MB / 273.6MB`
  - `~27.26MB / 273.6MB`
  - `~63.96MB / 273.6MB`

原因判断：
- 失败点不在 SigNoz 自身初始化
- 而在宿主 Docker mirror 链路吞吐太低，导致关键镜像始终未拉完
- 超时前连容器创建都没开始

结论：
- 卡在官方镜像获取
- 根因是“镜像供应链吞吐不足，`zookeeper` 镜像未能拉完，主部署没有进入运行态”

## task-012 `getredash/redash`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- 官方 self-host 路径的镜像/本地构建阶段

执行到的程度：
- 已按 `getredash/setup` 组织官方服务拓扑
- 支撑镜像已拉到：
  - `redash/nginx:latest`
  - `redis:7-alpine`
  - `pgautoupgrade/pgautoupgrade:17-alpine`
- 官方预构建应用镜像不可用后，又切到官方源码 Dockerfile 本地构建

直接失败信号：
- `errors.log` 明确记录 Docker mirror mismatch：
  - `Host doesn't match cfgHost=registry-1.docker.io host=docker.m.daocloud.io`
- `redash/redash:26.3.0` 始终没有成功 materialize
- 本地构建也卡在慢速上游依赖获取，尤其是 Databricks ODBC 驱动下载和前端依赖阶段

原因判断：
- 不是 Redash 服务启动后报错
- 而是官方镜像路径被宿主镜像链路拦住，本地兜底构建又同样受网络吞吐拖累

结论：
- 先失败于官方应用镜像获取，再失败于本地官方 Dockerfile 构建
- 根因是“Docker mirror 行为异常叠加慢速依赖下载，导致应用镜像始终不可用”

## task-013 `elastic/kibana`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- 官方 Elastic 本地 Docker 路径的镜像获取阶段

执行到的程度：
- 已按官方本地安装思路准备 `Deliverable/kibana/`
- 端口已选定
- 尝试过两次主部署

直接失败信号：
- 第 1 次明确失败：
  - `failed to copy ... cloudflarestorage.com ... EOF`
- 第 2 次改成 `COMPOSE_PARALLEL_LIMIT=1` 后虽有推进，但大层依旧未完成
- `summary.md` 明确写到 `docker.elastic.co` 拉取未完成

原因判断：
- 这是典型的 Elastic 官方 registry 大镜像下载失败
- 没进入容器创建，更没进入 Kibana HTTP 验证

结论：
- 卡在 `docker.elastic.co` 镜像层获取
- 根因是“官方 registry 拉取大层时直接 EOF，串行重试后也仍未完成下载”

## task-014 `OpenSearch-Dashboards`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- `Phase 4` 官方 Docker 部署拉取 OpenSearch 主镜像阶段

执行到的程度：
- 已准备：
  - `opensearchproject/opensearch:3.6.0`
  - `opensearchproject/opensearch-dashboards:3.6.0`
- 交付物和失败说明文件都已写出

直接失败信号：
- `errors.log` / `summary.md` 明确记录：
  - 约 24 分钟后主层仍只有 `372.2 MB / 1.048 GB`

原因判断：
- 没有出现应用级报错
- 单纯是 OpenSearch 大镜像在当前网络吞吐下太慢，无法在剩余预算内完成后续启动和审计

结论：
- 卡在官方 OpenSearch 镜像获取
- 根因是“大镜像吞吐过低，主部署无法进入 live verification”

## task-015 `Graylog2/graylog2-server`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- Graylog 7 官方 Docker Compose 的 Data Node 镜像拉取阶段

执行到的程度：
- 官方 Compose 所需 MongoDB、Data Node、Graylog 拓扑已准备
- 源码也通过 GitHub codeload 补齐到 `Deliverable/graylog/source`

直接失败信号：
- `errors.log` 记录：
  - `graylog/graylog-datanode:7.0` 大层只到 `159MB / 1.227GB`

原因判断：
- 失败不在 Graylog 配置或初始化
- 而在 Data Node 镜像体量大、吞吐低，导致压根没进入容器启动阶段

结论：
- 卡在官方 Data Node 镜像拉取
- 根因是“Graylog 7 关键镜像过大，当前环境吞吐不足以支撑主部署启动”

## task-018 `gitlabhq/gitlabhq`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- 官方 GitLab Self-Managed Docker Compose 拉镜像阶段

执行到的程度：
- 已准备官方 Docker Compose 资产
- 已将稳定 CE tag 固定到 `18.11.0-ce.0`
- 也已通过 codeload 补齐源码快照

直接失败信号：
- `errors.log` / `summary.md` 记录：
  - 最大层 `25.17MB / 1.766GB`
  - 次级层也未完成：`22.02MB / 29.73MB`、`15.73MB / 18.53MB`
- 未创建任何容器

原因判断：
- 这是最典型的大镜像吞吐失败之一
- GitLab CE 体量太大，当前网络下连 pull 都不现实，更不可能进入初始化

结论：
- 卡在官方 GitLab CE 镜像获取
- 根因是“多 GB 级镜像在当前网络吞吐下不可行，主部署未能进入容器创建”

## task-019 `mattermost/mattermost`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- 官方 Docker Compose 路径的镜像拉取与源码补档阶段

执行到的程度：
- 已准备官方 `mattermost/docker` 的 compose 资产和 `.env`
- 已创建 bind mount 目录
- 也尝试了补 `mattermost/mattermost` 源码快照

直接失败信号：
- `errors.log` 明确有两类问题：
  - `chown -R 2000:2000` 需要 `sudo`，当前 shell 无法完成
  - 更核心的是吞吐问题：
    - 官方镜像大层 `12.58MB / 569MB`，9 分钟后仍极慢
    - codeload 源码包也只有约 `17MB`，同样未补齐

原因判断：
- `sudo chown` 权限不足是一个环境约束，但不是最主要阻塞
- 真正压死任务的是 Docker Hub 与 GitHub codeload 两边都过慢
- 因此主部署没有成为 runnable 实例

结论：
- 卡在官方镜像拉取 + 源码补档
- 根因是“镜像和源码两条网络路径都过慢，外加官方建议的 `chown` 步骤在当前权限模型下无法完整执行”

## 汇总结论

这 7 个 `COMPLETED_FAILED` 项目有很强共性：

1. 绝大多数失败都不是应用业务错误
- `signoz`
- `redash`
- `kibana`
- `opensearch-dashboards`
- `graylog`
- `gitlab`
- `mattermost`

2. 最主导的根因是供应链/吞吐
- Docker Hub / `docker.elastic.co` / OpenSearch / GitHub codeload 这些外部路径都偏慢
- 其中 `gitlab`、`graylog`、`opensearch-dashboards`、`mattermost` 都是“大镜像或双重大传输”问题

3. `redash` 相比其他项目多了一层镜像镜像站异常
- 不仅慢，而且 Docker daemon mirror 还出现 `Host doesn't match` 这类明确异常

整体上看，这一批“部署失败”项目的主要根因很集中：
- 大镜像拉取过慢
- Docker mirror / registry 路径异常
- 部分项目还叠加了慢速源码补档

这意味着提升下一批成功率，优先级最高的不是单项目业务修复，而是：
- 提升 Docker registry / mirror 的稳定性和吞吐
- 避免在同一任务里同时争抢 GitHub 大源码下载与大镜像下载
