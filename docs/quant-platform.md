# 量化基础操作说明

本轮是研究与模拟交易基础设施升级，不是实盘验收。所有命令从仓库根目录执行。

## 1. 数据库迁移

备份并确认 `backend/.env` 的 `DATABASE_URL` 指向目标数据库，再执行：

```powershell
python -m alembic upgrade head
```

迁移 `20261004_0004` 增加证券身份、代码有效期、成分区间和行情版本；`0005` 增加模拟执行事件、成交与现金流水。现有行情和订单不删除、不自动伪造历史版本或历史成交。旧 SQLite 的迁移步骤仍在 DEVELOPMENT.md。

没有配置 SQLAlchemy 数据库时，旧 SQLite 工作台仍能运行，但不具有新的 PIT/账本能力。不要直接删除旧库；完成迁移、行数/余额核验和备份恢复演练后再退役。

## 2. 证券身份与当时可见数据（PIT）

先从可信供应商整理主数据，再执行：

```powershell
python backend/scripts/quant_platform.py import-master path/to/master.json
```

JSON 示例（证券 ID 是供应商或运营方维护的永久身份，不是股票代码）：

```json
{
  "securities": [{"id": "security-example", "market": "US", "currency": "USD"}],
  "aliases": [{"security_id": "security-example", "symbol": "EXAMPLE", "valid_from": "2026-01-01", "available_at": "2025-12-01T00:00:00Z"}],
  "memberships": [{"security_id": "security-example", "universe": "research", "valid_from": "2026-01-01", "valid_to": "2026-10-01", "available_at": "2025-12-01T00:00:00Z"}]
}
```

区间为左闭右开；相同记录可重复导入，记录不可原地改写。代码映射重叠会在行情导入时报错，修改有效期须经运营方核验，不要直接追加相互矛盾的开放区间。

SQLAlchemy 行情导入会保留修订链。`store.list_bars_as_of(security_id, as_of, source=..., known_at=...)` 按供应商可用时间选择版本，`known_at` 可进一步限制本系统入库时间。没有可信 `available_at` 的 Yahoo 回填使用实际入库时刻。

未映射代码得到标记为 provisional 的身份，不能把它当成消除了代码复用/幸存者偏差；之后导入主数据也不会静默重绑既有版本。假日或收市前日线进入隔离状态，PIT 查询排除该版本；兼容的 `daily_bars` 最新值视图仍供旧工作台使用，因此旧预测路径并未自动变成 PIT 回放。

US/JP/HK 的会话日期由 `exchange-calendars` 提供。日历仍需随官方休市调整维护，不能替代供应商数据质量协议。

## 3. 多资产组合回测

```powershell
python backend/scripts/quant_platform.py backtest examples/portfolio-replay.json --output backend/storage/portfolio-replay.json
```

示例为合成数据，只验证引擎行为，不代表真实策略收益。输入包含：

- `benchmark`：连续美国交易日的基准日线。
- `assets`：以永久 ID 为键，包含 `market: US`、`currency: USD`、`sector` 和 `bars`。
- 日线的 `open/close` 是原始价；`adj_close` 仅用于信号/基准收益；`available_at` 必须是带时区的可信时间戳。
- `memberships`：历史成分的身份、生效区间和可用时间。严格模式默认为开启。
- 可选 `signals`：`security_id/date/score/available_at`，在截点前记录的模型分数替代动量排名。
- 可选 `actions`：`security_id/date/type/value`；split 为拆分倍数、dividend 为每股现金、delisting 为每股兑付金额。
- `config`：初始资金、回看/调仓周期、持仓数、单股/行业/换手上限、成交量参与率和成本参数。

信号在 t 收盘形成，数量在 t+1 开盘撮合。缺失持仓估值会报错；未成交数量当日失效。输出包含净值、现金、逐笔成交、公司行动、成本、回撤、Sharpe、历史 VaR/ES。

限制：仅 USD 美股多头；日成交量用于事后容量近似，不代表开盘可成交量；持仓上限为信号时约束，不保证跳空后权重。分红在输入事件日记现金，未实现应收款、结算、税费或券商排队。输入是冻结的数据版本，必须由数据供应方保证历史复权可用性；引擎不会自动从版本库拼出逐时点修订数据。不要用今天的完整股票池/复权历史冒充真正的历史截面。

## 4. 模型注册与前向观察

设置 `DATABASE_URL` 后，数据库是模型元数据和 active 选择的唯一权威；故障时不会退回文件中的旧 active 选择。模型文件仍保存在受信任的 `MODEL_REGISTRY_DIR`。

```powershell
python backend/scripts/quant_research.py import-registry
python backend/scripts/quant_research.py list
python backend/scripts/forward_worker.py --once
# 前台常驻，每小时检查；不会拉行情，需要 ingestion worker 提前更新本地数据
python backend/scripts/forward_worker.py
# 明确启用：样本足够且误差退化时停用当前模型，让在线路径回退到基线
python backend/scripts/forward_worker.py --disable-degraded
```

已有文件模型需要先导入，再按原有验证门槛显式 activate；导入不会自动激活。相同 manifest 可重复导入，内容变更被拒绝。

监控将当前模型预测归档，等待标签成熟后评分，同一模型/预测周期只统计不重叠观察，最近最多 60 条，默认至少 20 条。MAE 超过零超额收益基线 10% 为退化策略；这不是统计显著性检验。过期/未来日线阻止自动停用。切换模型用期望版本检查，避免旧监控结果覆盖新激活选择。文件模式限单操作进程。

查看 `MODEL_REGISTRY_DIR/monitoring/latest.json` 与进程日志。未实现邮件告警、任务调度器安装或自动重训；生产运行需外部进程管理和告警接入。20 日非重叠样本积累需要很长时间，不能把样本不足解释为通过验收。

## 5. 模拟账本和对账

SQLAlchemy 模拟订单的创建/取消追加事件，确认成交与持仓、现金和流水在同一事务提交，重复确认不重复成交。账本从升级后第一笔成交前的余额建立期初，不声称重建了旧历史。

```powershell
python backend/scripts/quant_platform.py reconcile --portfolio primary
python backend/scripts/quant_platform.py reconcile --portfolio primary --statement path/to/statement.json
```

对账单格式：`{"currency":"USD","cash":9900,"positions":{"EXAMPLE":1}}`。
不传对账单仅核对内部现金；传入后增加现金/数量差异检查。未开始记账或存在差异时退出码为 1；命令不会自动修复余额或发单。当前 Fill 限一单一次完整模拟成交，不是券商部分成交适配器；数据库记录也不是防管理员篡改的外部审计存储。

## 6. 剩余实盘前置条件

仍需可信历史成分/退市/修订数据、逐时点特征快照、独立最终留出集与多重试验控制、跨币种汇率风险、券商沙盒/部分成交/外部对账、权限审批，以及 PostgreSQL 并发/备份恢复演练。此次未连接实盘账户，未执行本机业务库迁移或启动常驻任务。
