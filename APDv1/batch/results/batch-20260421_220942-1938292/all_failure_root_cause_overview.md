# 全部失败项目根因总览

批次：`batch-20260421_220942-1938292`

说明：
- 当前 `batch/results/batch-20260421_220942-1938292/` 中只落账到 `task-019`
- 本总览仅覆盖 `failure.txt` 已记录的 `12` 个失败任务

目标：
- 把所有失败项目压缩成一页
- 让人一眼看出每个项目“失败类型、卡点、根因、优先处理方向”

## 一眼看懂

本批次失败项目共 `12` 个，可归为 4 类：

1. 主部署阶段的镜像/源码供应链太慢
- `it-novum/openITCOCKPIT`
- `SigNoz/signoz`
- `getredash/redash`
- `elastic/kibana`
- `opensearch-project/OpenSearch-Dashboards`
- `Graylog2/graylog2-server`
- `gitlabhq/gitlabhq`
- `mattermost/mattermost`

2. 首次运行暴露真实缺口，修复重建又吃满预算
- `mikaku/Monitorix`

3. 实际部署已成功或几乎成功，但卡在 `Phase 6` 纠偏/终态落账
- `apache/skywalking`
- `apache/superset`
- `go-gitea/gitea`

4. 主部署已成功，但被错误的源码硬前置契约拖住，尚未进入主审计
- `metabase/metabase`

## 总表

| task_id | 项目 | 状态 | 卡住阶段 | 一句话根因 | 归类 | 优先级 |
|---|---|---|---|---|---|---|
| task-001 | `it-novum/openITCOCKPIT` | `TIMED_OUT` | `Phase 4` compose 拉镜像 + 源码补档 | 镜像获取与源码快照都慢且多次中断，超时前没进入容器创建 | 供应链/吞吐 | 高 |
| task-002 | `mikaku/Monitorix` | `TIMED_OUT` | 主部署修复后的第 2 次重建 | 第 1 次运行暴露 `invalid group` 和缺少 `ss/iptables`，修复后重建被慢速 `apt` 吃满预算 | 运行态缺口 + 重建慢 | 中 |
| task-005 | `SigNoz/signoz` | `COMPLETED_FAILED` | 官方 compose 拉镜像 | `zookeeper` 镜像长期只拉到局部，容器都没创建 | 供应链/吞吐 | 高 |
| task-009 | `apache/skywalking` | `TIMED_OUT` | `Phase 6` 纠偏重放 | 首轮 portable 验证已成功，但发现命中错误端口；修复后二次重放又撞上 BanyanDB 端口冲突 | Phase 6 纠偏超时 | 高 |
| task-010 | `apache/superset` | `TIMED_OUT` | `Phase 6` 通过后的终态落账 | Phase 6 worker 和 final audit 都已完成，但父流程未在时限内写出终态 | 收尾编排超时 | 高 |
| task-011 | `metabase/metabase` | `TIMED_OUT` | 主部署成功后的错误契约补全 | 应用已成功并通过验证，但流程仍把 `source/` 视为硬前置，导致主审计被不必要地推迟 | 错误的源码硬前置契约 | 高 |
| task-012 | `getredash/redash` | `COMPLETED_FAILED` | 官方镜像失败后转本地构建 | mirror mismatch 让官方镜像不可用，本地官方 Dockerfile 构建又受慢速依赖下载拖住 | 供应链/吞吐 | 高 |
| task-013 | `elastic/kibana` | `COMPLETED_FAILED` | `docker.elastic.co` 拉镜像 | 第 1 次直接 EOF，第 2 次串行拉取仍未完成大层 | 供应链/吞吐 | 高 |
| task-014 | `opensearch-project/OpenSearch-Dashboards` | `COMPLETED_FAILED` | OpenSearch 主镜像拉取 | 24 分钟仍只有 `372.2MB / 1.048GB`，主部署无法进入 live verification | 供应链/吞吐 | 高 |
| task-015 | `Graylog2/graylog2-server` | `COMPLETED_FAILED` | Graylog Data Node 镜像拉取 | 关键 Data Node 镜像大层只到 `159MB / 1.227GB` | 供应链/吞吐 | 高 |
| task-017 | `go-gitea/gitea` | `TIMED_OUT` | `Phase 6` 与 final audit 通过后收尾 | 主审计和 final audit 都已 `PASS`，但父流程在经验落账/清理/终态前超时 | 收尾编排超时 | 高 |
| task-018 | `gitlabhq/gitlabhq` | `COMPLETED_FAILED` | GitLab CE 大镜像拉取 | 最大层仅 `25.17MB / 1.766GB`，无容器创建 | 供应链/吞吐 | 高 |
| task-019 | `mattermost/mattermost` | `COMPLETED_FAILED` | 官方镜像拉取 + 源码补档 | Docker Hub 和 GitHub codeload 两边都太慢，且官方 `chown` 步骤受当前权限限制 | 供应链/吞吐 | 高 |

## 根因拆解

### 1. 最主要的问题不是项目代码，而是宿主供应链

这一类占了绝大多数：

- `openITCOCKPIT`
- `SigNoz`
- `Redash`
- `Kibana`
- `OpenSearch-Dashboards`
- `Graylog`
- `GitLab`
- `Mattermost`

共性特征：
- 大镜像拉取长期停在局部进度
- GitHub codeload / `git clone` 也常常同步变慢
- 任务还没进入真正的业务初始化，就已经耗尽预算

### 2. 真正的应用/运行态问题并不多，但一旦出现会放大时间成本

典型项目：
- `Monitorix`

特点：
- 第 1 次部署其实已经跑起来并给出明确错误
- 修复后必须重建镜像
- 在当前慢速 apt / registry 环境下，修复验证成本明显偏高

### 3. 收尾编排问题在这批里很突出

典型项目：
- `SkyWalking`
- `Superset`
- `Gitea`

特点：
- 应用和 portable bundle 很多时候已经实际成功
- 真正输在：
  - Phase 6 纠偏重放
  - final audit 结果回写
  - 经验落账 / cleanup / terminal state 写入

这类项目离成功最近，优化收益最大

### 4. 交付契约本身也会拖慢本来已经成功的任务

典型项目：
- `Metabase`

特点：
- 应用已经可用，验证也已经通过
- 但流程仍把 `Deliverable/<project>/source/` 当成主审计前必备项
- 对 Metabase 这种官方镜像即可完成部署的项目，这个要求本应是可选的
- 结果把本来接近成功的任务拖成了超时

## 最值得优先处理的共性问题

如果目标是下一批次尽量提升成功率，优先级建议如下：

1. 先处理“实际上已成功，但收尾超时”的项目
- `superset`
- `gitea`
- `skywalking`

原因：
- 这三项离成功最近
- 不需要重做业务部署，只需缩短 `Phase 6` 纠偏和终态落账路径

2. 再处理“主部署成功但卡在错误源码前置”的项目
- `metabase`

原因：
- 这是典型的流程契约判断错误
- 如果能把 image-first 项目的 `source/` 明确改成可选，成功率会明显提升

3. 然后处理宿主供应链问题
- `openitcockpit`
- `signoz`
- `redash`
- `kibana`
- `opensearch-dashboards`
- `graylog`
- `gitlab`
- `mattermost`

原因：
- 这类失败几乎都发生在应用真正启动之前
- 不解决镜像源、registry、GitHub 大文件吞吐，下一批还会重复出现

4. 最后处理单项目运行态缺口
- `monitorix`

原因：
- 它不是纯网络问题，而是确实暴露了容器依赖缺口
- 但修好之后仍然受慢速 rebuild 影响

## 最终结论

这一批失败项目里，最关键的结论不是“很多项目部署错了”，而是：

1. 真正的主导问题是宿主环境对大镜像和大源码快照的吞吐不足
2. 有 3 个项目其实已经完成了绝大部分工作，失败只是因为 `Phase 6` 或终态回写太慢
3. 还有 1 个项目已经把应用跑通，却因为把本可选的 `source/` 错误当成硬前置而超时

如果只看最一目了然的根因排序：

1. Docker registry / GitHub codeload 吞吐不足
2. `Phase 6` 纠偏和终态落账过慢
3. 为满足交付契约而继续等待完整源码快照
4. 少数项目存在真实运行态缺口，需要修复后重建验证
