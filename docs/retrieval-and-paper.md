# pgvector 检索与本地模拟

本轮不连接任何券商，也不会提交实盘订单。已有代码基线 `4ac6f24` 已推送到
`origin/codex/ai-trading-workbench`；本轮升级在此基础上实现。

## 数据库

Compose 使用 PostgreSQL 17 + pgvector 0.8.1，绑定本机回环地址。
新卷 `stockpredictionai_stockpredictionai_pgvector_data` 与旧 Alpine 卷
`stockpredictionai_stockpredictionai_pgdata` 分离。**已有数据库必须先备份，再切换镜像，不能直接复用旧卷，也不要执行 `docker compose down -v`。**

本机已完成：旧库 custom-format 逻辑备份 → 独立测试库恢复 → 0003 至 0006 迁移 →
原有 20 张业务表行数校验（15,357 行一致）→ 新卷恢复并升级。
备份在忽略目录 `backend/storage/backups/stockai-before-pgvector-20261016.dump`，SHA256：
`8f40195912b3c1a555e35751138367e4361a4686dddee2a92e13dc3316c13b35`。
旧卷仍保留。备份含业务数据，请另外安全保存；本地磁盘上的同机备份不等于灾备。

新环境安装（已有库先备份）：

```powershell
python -m pip install -r backend/requirements.txt
docker compose up -d postgres
python -m alembic upgrade head
python backend/scripts/research_worker.py --once --snapshot-only
```

备份使用容器内 `pg_dump --format=custom --file=/tmp/backup.dump` 后 `docker cp`。
恢复演练必须 `createdb` 创建全新的目标库，再用 `pg_restore --no-owner --no-acl --exit-on-error`；
不要往已有业务库反复恢复。先比较旧业务表的行数，再检查关键业务记录和迁移版本。
回滚需要停用新写入并切回旧镜像/旧卷；切换后产生的新记录不会自动存在于旧卷，应先另行备份。

## 新闻、向量与证据问答

- 新闻接入沿用现有情绪页面/新闻工作进程，不自动抓取任意网页。
- 内容变化追加 `research_documents` 版本，不覆盖旧快照。历史查询只选截点前已知的最新版本。
- 情绪分析追加 `sentiment_observations`；分析实际完成时间不能被调用方回填为更早时间。
- 旧数据首次建立快照的时间为现在，不假装历史上已经可用。
- 向量以文档版本和模型配方唯一标识，1536 维；每条输入最多 8000 token。
- 后台工作进程用 PostgreSQL 行锁领取任务；失败指数退避，五次后转 failed；进程崩溃由事务回滚释放任务。
- 切换 `EMBEDDING_MODEL` 后运行 worker 会为新模型增量建索引，保留旧模型向量。
  当前允许 `text-embedding-3-small` / `text-embedding-3-large`，均固定 1536 维。
- 历史向量检索同时限制向量完成时间，不把今天生成的向量伪装成过去的在线能力。

配置 `backend/.env` 的 `OPENAI_API_KEY` 后运行：

```powershell
python backend/scripts/research_worker.py --once --batch-size 20
# 持续处理，Ctrl+C 停止；不会自行安装系统服务
python backend/scripts/research_worker.py --interval 60
# 操作员确认后重新处理终止失败任务
python backend/scripts/research_worker.py --once --retry-failed
```

AI 助手页新增投研证据面板。接口：`GET /research/status`、`POST /research/search`、
`POST /research/answer`，沿用本机/API token 访问控制。请求包含 `query`、可选 `symbol`、
带时区的 `as_of`、`mode`（keyword/vector/hybrid）；问答另支持 `language`。

关键词模式无需 embedding API；缺少生成密钥时只返回证据，不编造答案。没有证据则明确返回
`insufficient-evidence`。模型引用必须是返回文档 ID，并且引文必须逐字存在于证据中。
这只是引用完整性校验，不等于事实蕴含性或投资建议质量保证。成功的检索问答记录保存在
`research_answers`。提供给外部模型的是问题和检索片段，请确保内容具有相应使用权限。

目前用精确余弦检索作为正确性基线，没有贸然开启近似索引；关键词是子串匹配而不是 BM25。
混合模式以 RRF 融合两种排名。余弦距离阈值 0.8 尚未用真实标签校准。
文档不分块、向量截断长文，适合当前新闻标题/摘要；完整研报需要下一轮分块和覆盖评测。

## 固定检索评测

```powershell
# 使用已迁移的专用测试库，不使用业务库
$env:RETRIEVAL_EVAL_DATABASE_URL = 'postgresql+psycopg://quant_test:quant_test@127.0.0.1:55439/quant_test'
python backend/scripts/retrieval_eval.py examples/retrieval-eval.json
# 需要有效 API Key，产生 embedding 调用费用
python backend/scripts/retrieval_eval.py examples/retrieval-eval.json --modes keyword vector hybrid
```

每次创建并清理随机隔离 schema；报告 precision@5（固定分母 5）、recall@5、MRR、
无答案正确率、P95、索引和查询 token 数。费用需按实际供应商价格换算，未虚构金额。
合成集只有 8 篇/11 问，覆盖中英日和一个无答案问题，是冒烟基线而非质量证明。
下一步需人工标注真实、有授权的新闻，加入跨语言同义问法、困难负例、股票歧义、修订与时效测试；
冻结标签后再比较模型，不能边改测试答案边宣称指标提升。

## 本地模拟与模型信号

```powershell
# 使用专用研究库。示例是合成行情，不代表实际收益。
python backend/scripts/paper_cycle.py examples/portfolio-replay.json --strategy demo-v1
# 对真实 PIT 数据，接入现有模型注册目录中已记录的前向预测
python backend/scripts/paper_cycle.py path/to/pit-dataset.json --strategy candidate-v1 --registry path/to/registry --horizon 5
```

数据格式见 `examples/portfolio-replay.json`。使用 `--registry` 时资产必须带 `symbol`；
自动把归档的 `excess_return_pct` 转成排名分数，检查模型清单、训练截止日、创建时间和实际归档时间。
归档在收盘后生成的信号保守地移至下一交易日的信号截点，再按次日成交规则执行；不会回填到更早的成交日。
同股票/同信号日冲突会失败，不静默选择有利预测。没有有效前向归档会明确失败。

直接传 `signals` 时每条必须包含 `security_id/date/score/available_at/model_run_id/trained_until/model_available_at`。
这类外部输入仍依赖提供方可信；本系统不能证明外部训练数据的真实性。
模型信号和动量基线使用相同手续费、滑点、容量限制；不自动选择收益最高的策略或重新训练。

`paper_cycles` 保存输入快照、哈希、完整成交/净值、模型 ID 和基线指标；逐日重建现金、持仓及净值并对账。
相同策略/日期重复执行幂等，修改过去输入、配置或重放行为会拒绝，需要显式创建新策略版本。
每天准备好新增的完整 PIT 数据后重复运行即可追加检查点；当前没有自动行情导出或无人值守调度，
不能把一次历史重放称为持续前向模拟。模型退化监控沿用 `docs/quant-platform.md` 中的 forward-monitor，
目前与本地检查点分开运行，不会自动用新模型替换旧模型。

`trading/local_sandbox.py` 提供纯本地 submit/fill/cancel 事件重放和重启对账；测试覆盖部分成交、
重复事件、冲突事件、超额成交、余额不足、撤单后成交和恢复后状态一致性。
它是验证组件，不是券商适配器，不声称具备真实交易所撮合、网络事件乱序或跨系统对账能力。

## 验收及尚未完成的外部条件

```powershell
$env:TEST_POSTGRES_URL = 'postgresql+psycopg://quant_test:quant_test@127.0.0.1:55439/quant_test'
python backend/scripts/run_checks.py
npm run typecheck
npm run build
```

CI 使用真实 pgvector 服务执行迁移与集成测试。没有设置测试 URL 时，PG 用例会跳过。
本次本机 PostgreSQL 向量算子使用确定性测试向量验证过滤、版本选择和可用时间，不把它冒充语义质量评测。
当前业务库新闻为 0，且未配置 OpenAI Key；因此真实 embedding、LLM 输出质量和真实新闻集对比尚待完成。
持续样本外表现需要后续逐日积累，不能由合成回放替代。券商连接明确留到未来范围。

实现参考：[pgvector](https://github.com/pgvector/pgvector)、
[OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)。
