# 小规模评测数据集的经验系统覆盖情况

数据集：

- `batch/eval/datasets/apdv1_vs_bare_codex_small.jsonl`

经验库：

- `.codex/experience/catalog.json`
- `.codex/experience/index/**.jsonl`
- `.codex/experience/details/**.jsonl`

## 结论

这 12 个样本不是全部都有项目级经验记录。

- 明确项目级经验较强：8 个
- 只有间接同栈/组件经验：1 个
- 暂无明显经验命中：3 个

这意味着当前数据集既能体现 APDv1 的经验沉淀优势，也保留了若干 blind/generalization 样本。若实验目标是最大化展示经验系统收益，可以替换掉无经验命中的样本；若实验目标是公平评估泛化能力，则应保留一部分无经验样本。

## 覆盖表

| Project ID | Category | Experience Coverage | Evidence |
| --- | --- | --- | --- |
| `easy_image_first_filebrowser` | `easy_image_first` | 项目级强命中 | `EXP-FILEBROWSER-DEPLOY-001`, `EXP-FILEBROWSER-RUNTIME-001` |
| `easy_image_first_minio` | `easy_image_first` | 项目级强命中 | `EXP-MINIO-DEPLOY-001`, `EXP-MINIO-REGISTRY-001`, `EXP-MINIO-BUNDLE-001` |
| `db_web_wordpress` | `db_backed_web_app` | 项目级强命中 | `EXP-WORDPRESS-RUNTIME-001`, `EXP-WORDPRESS-BUNDLE-001`, `EXP-WORDPRESS-BUNDLE-002` |
| `db_web_gitea` | `db_backed_web_app` | 项目级强命中 | `EXP-GITEA-DEPLOY-001`, `EXP-GITEA-001`, `EXP-GITEA-PORTS-001`, `EXP-GITEA-BUNDLE-001` |
| `multi_service_superset` | `multi_service_business_app` | 项目级中等命中 | `EXP-SUPERSET-PORT-001`, `EXP-SUPERSET-BUNDLE-001` |
| `multi_service_appwrite` | `multi_service_business_app` | 项目级单点命中 | `EXP-APPWRITE-PULL-001` |
| `k8s_pipeline` | `kubernetes_helm_operator` | 项目级强命中 | `EXP-TEKTON-DEPLOY-001`, `EXP-TEKTON-VERIFY-001`, `EXP-TEKTON-BUNDLE-001` |
| `k8s_argo_cd` | `kubernetes_helm_operator` | 项目级单点命中 | `EXP-ARGOCD-KIND-PROXY-001` |
| `observability_grafana` | `observability_stack` | 无 Grafana 项目级命中；有间接组件经验 | CubeFS 经验中包含 Grafana/Prometheus 监控组件拉取与验证经验，但不是 `grafana/grafana` 项目经验 |
| `observability_signoz` | `observability_stack` | 暂无明显命中 | 未发现 `signoz/signoz` 或 `signoz` 项目级经验记录 |
| `ambiguous_library_pdfjs` | `ambiguous_or_library_target` | 暂无明显命中 | 未发现 `mozilla/pdf.js`, `pdf.js`, `pdfjs` 项目级经验记录 |
| `external_prereq_octobercms` | `external_prerequisite` | 暂无明显命中 | 未发现 OctoberCMS / `octobercms` 项目级经验记录 |

## 如何体现经验沉淀优势

如果主目标是证明经验系统带来的提升，建议报告时按覆盖层级分组：

1. `project_experience`: 有项目级经验记录。
2. `related_stack_experience`: 没有项目级经验，但有同栈、同组件、同失败模式经验。
3. `no_experience`: 没有明显经验命中。

然后分别比较 APDv1 local-run 与 Bare Codex：

- 在 `project_experience` 组，APDv1 是否更快定位官方路径、少踩已知坑、验证更完整。
- 在 `related_stack_experience` 组，APDv1 是否能复用同类经验而不是机械套用。
- 在 `no_experience` 组，APDv1 是否仍然依靠流程约束保持稳定，还是 token/时间开销偏大。

## 如果想更强地展示经验优势

可以把暂无命中的样本换成已有经验记录的项目，例如：

- 用 `gocd`、`woodpecker`、`jenkins`、`apisix`、`nextcloud`、`logstash`、`shipwright` 等替换无经验命中的样本。
- 保留 1-2 个无经验样本作为泛化对照，不建议全部换掉。

更平衡的选择是：

- 8-9 个项目级经验样本
- 1-2 个相关栈经验样本
- 1-2 个无经验样本

这样既能体现经验沉淀价值，也不会让评测变成只考“背过答案”的项目复现。
