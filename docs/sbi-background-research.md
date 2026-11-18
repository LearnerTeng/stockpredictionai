# SBI 导入、分析重放与后台运行

## 从 SBI 保有ファンド更新持仓快照

已登录 SBI 时，在「保有ファンド」使用「CSVダウンロード」，保留原文件名。下载目录中的文件含个人持仓信息，请保存在本地。

`python backend/scripts/sbi_holdings_snapshot.py <CSV路径>` 预览基金笔数及金额。加入 `--apply` 后更新现有 NISA 仓位。命令核对成长枠与积立枠、两组小计、账户合计及库里的基金映射。同份导出重复提交会跳过。更新事务保存各仓位的旧值及导出里的待卖口数。此流程记录导出时间，独立的成交增量导入仍使用其已核对的快照截止日。

## SBI 累计收益与基金履历

总览可在 **SBI NISA** 和 **模拟盘** 间切换。SBI NISA 使用 SBI「トータルリターン」的算出日和日元累计收益，详情按基金代码与 NISA 预存类别区分。基金「履历」中的口数和净值来自有事件的日期。收益曲线逐日积累已导入的算出日，缺失日期无数据。持仓快照的导出日期单独显示。

复用时，在 SBI「銘柄一覧」选择「全期間（累計）」并下载 CSV。到项目总览或我的组合里的 **同步 SBI 日数据**，填入 SBI 的算出日和页面上的整个累计收益金额，选取收益 CSV。也可同时选同批的「保有ファンド」CSV 更新当前仓位。先预览，再写入本地数据库。同一天只有一个收益点。页面每分钟查询已入库数据。

若要同步基金交易履历，在各基金「履歴」导出全期明细。用本地 JSON 记录基金与导出的对应关系，例如 `{"XXXXXXXX":{"name":"示例基金","history":"DetailHistoryxxx.csv"}}`，键是「履歴」URL 末尾的基金代码。传给 `python backend/scripts/sbi_returns_import.py <累计收益CSV> --as-of <算出日> --total <页面显示的日元总收益> --funds <映射JSON>`。可加 `--holdings <持仓CSV>`，核对预览后再加 `--apply`。首次导入或基金清单变化要核对代码映射。持仓自动写入要求现有仓位匹配，已有成交增量账本的账户需先对账。浏览器登录和导出由当前会话完成，后台可用已入库的数据。

## 首次启用 SBI 导入

1. 启动项目 PostgreSQL，安装依赖，在项目根目录执行 `python -m alembic upgrade head`。导入使用现有的 JPY、`read_only`、`nisa` 类型持仓。可从持仓页的账户选择器确认账户，或用 `GET /portfolios` 查看 ID。
2. 在 `backend/.env` 设置 `SBI_IMPORT_DIR` 为私有绝对路径，例如 `C:/private/sbi-import`。以 ID 为 `nisa` 为例，在该目录下建 `nisa/config.json`、`nisa/trades/` 和 `nisa/nav/`。不同 SBI 账户应使用不同项目账户 ID 和独立目录。
3. 复制 [配置样例](../examples/sbi-import-config.json) 到账户目录的 `config.json`，把合成示例值改为自己核对过的数据。`snapshot_through` 是日本时间下截图持仓已覆盖的最后一个完整约定日（含当日）。只覆盖半天时，先取得可确认的完整日快照。截图记录没有可信截止日时，使用这个配置字段确认，勿用数据库更新时间代替。首次初始化后截止日锁定。可在核对后更新 `holdings_confirmed_through`，表示从基准日起的全部成交已核对到哪天。导入单份 CSV 不会自动推进此日期。
4. `funds` 逐一映射现有持仓的 symbol、现有 bucket（如 `growth`）及 CSV 中准确的基金名和 SBI 預り区分。相同基金分属两个 bucket 时用两个项目持仓 symbol。可预先添加新基金映射。可选的 `news_symbols` 用于从已采集的公开新闻中附带相关标的证据，通知会标出关联标的。
5. 启动 `./start-all.ps1`。后台首次立即扫描，以后每分钟扫描。也可运行 `python backend/scripts/sbi_worker.py --once`。将完整文件放入对应目录，持仓页的 **SBI 导入与净值提醒** 显示导入结果、待核对文件和通知状态。

### 成交与净值文件

- 从 SBI 投資信託「取引照会」→「約定履歴」导出 CSV。支持 UTF-8（含 BOM）和 CP932。读取 `約定日,ファンド名,預り区分,取引種別,約定数量,約定単価,受渡日,受渡金額`。日期用 `YYYY/MM/DD` 或 `YYYY-MM-DD`。成交数量是整数口，价格和金额为无单位后缀的正数，带逗号的数值须正确加 CSV 引号。匹配的是国内日元基金普通买入、卖出或有明确正额成本的分配金再投资。格式差异、外币、移管、无法排序的同日买卖或含义不明的记录会显示错误。现有兼容性通过按官方指南构造的脱敏文件验证，实盘账户原始文件仍需首次核对。
- 截止日及以前的成交跳过。相同文件内容即使改名也只处理一次，同一份导出中的相同行按笔数保留。另一份文件与账本有重叠时，整份文件先等待持仓页逐组核对。对照约定履历，为每组输入这份文件中此前尚未计入的笔数，然后保存。重叠确认与交易生效分两步，下一次扫描会重新检查当前账本。对已导入成交有更正时，需要先核对原始交易及持仓，避免把更正当成新增。
- 净值来源需独立提供。把基金公司发布或自有可信数据源输出的净值整理为 CSV 放到 `nav/`。列名为 `symbol,nav_date,available_at,jpy_per_10000`，例如 `SYNTH-FUND,2026-11-12,2026-11-12T20:00:00+09:00,9300`。净值按每万口的日元金额输入，时间须带时区。系统用 **份额 × 净值 ÷ 10,000** 计算市值，买入按已核对受渡金额计入成本，卖出按移动平均成本减少持有成本。净值更新不会修改份额。持仓估值适用于本地跟踪，账户现金和券商税务损益需以券商记录为准。
- 净值跌幅达到 `nav_drop_pct`（默认 5%）时，以最近两次导入的净值计算，界面会保留近期异常与当时可用的新闻。填写 `SBI_ALERT_RECIPIENTS` 并配置现有 SMTP 项后可同时发送邮件。已确认发送的事件重启后不会重发。若发信阶段断电或 SMTP 回执不明确，事件显示 `unknown`，需要先查邮箱和 SMTP 记录。每个事件最多自动尝试一次，邮件最终送达由 SMTP 服务决定。

SBI 官方导出入口见 [投資信託 約定履歴指南](https://search.sbisec.co.jp/v2/popwin/guide/tool/fund_browser/09_status/trade-history.html)。导出与净值文件由本地目录提供，交易和登录仍由 SBI 官网处理。

## 后台和 Windows 登录启动

- 交互启动运行 `./start-all.ps1`。用 `Ctrl+C` 或另开终端运行 `./start-all.ps1 -Stop` 结束本次启动器管理的进程。
- Windows 用 `./windows-startup.ps1 -Action Install` 注册当前用户登录任务。可用 `-Action Status` 查看，`-Action Start` 手工触发，`-Action Stop` 正常关闭，停稳后用 `-Action Uninstall` 移除。应从长期使用的主目录注册。任务在登录后 30 秒隐藏运行，数据库尚未就绪时由计划任务按两分钟间隔重试，最多五次。
- 若项目的本机 PostgreSQL 尚未连接，Windows 启动器会按需在后台启动已安装的 Docker Desktop，等待 Linux 引擎（120 秒），只启动本目录已有的 Compose `postgres` 容器，再等待数据库认证连接（60 秒）。此电脑仍使用 `127.0.0.1:15432` 和原有数据卷。依赖启动日志见 `backend/local_data/supervisor/launcher.log`。超时会退出并由计划任务重试。若 Docker Desktop 有许可或 UAC 提示，请先在该应用内完成提示。
- 连接或迁移错误见 `backend/local_data/supervisor/launcher-error.log`。若要暂停下次登录启动，运行 `Disable-ScheduledTask -TaskName StockPredictionAI`。要取消等待依赖或关闭已运行的应用进程，再执行 `./windows-startup.ps1 -Action Stop`。可用 `Enable-ScheduledTask -TaskName StockPredictionAI` 恢复登录启动。停止应用时，Docker Desktop 和 PostgreSQL 继续运行。
- 运行状态在 AI 助手页的运行状态区以及 `GET /runtime/status` 查看。进程日志在 `backend/local_data/supervisor`。单个进程退出按指数退避独立重启，最长五分钟。状态包含最近成功循环时间，新闻另显示最近完成的增量任务。被中断的新闻任务会在 PostgreSQL 释放原 worker 的互斥锁后重新接手。运行状态同时标出新闻抓取是否进行中。
- 启动前需要可连接的 PostgreSQL、匹配的 Alembic 版本、Python 依赖和已执行 `npm ci` 的 Node 项目。

## 固定时点分析与情绪评估

- 建议任务入队时冻结分析时点、持仓时间、行情和新闻可用时间、规则、提示词版本及规则输出。报告显示分析时间，`GET /advice/jobs/<id>/replay` 从存档重放规则并返回原有解读。旧任务优先使用原有 freshness，否则使用创建时点。交易日使用 US/JP 交易所日历。NISA 持仓核对超过 14 个日历日或 NAV 缺失/超过一个发布日容差时显示证据不足。
- 在情绪页的 **新闻情绪的增量预测评估** 选择库中已有的美日股及日期。美股以 SPY 为基准，日股以 TOPIX ETF（1306.T）为基准。两组使用相同标的、5/20 个交易日目标、滚动训练样本和测试点，以收盘后 30 分钟为信息截止。仅使用截止前已归档的价格、文章版本及已完成的情绪推理。用页面上的重跑按钮按原模型、提示词和评估截止时点复跑。新模型只有积累当时可用的历史推理后才有样本。
- 分别报告 US/JP 的平均绝对误差（百分点）、方向命中率、配对样本数和数据覆盖。覆盖不足时显示历史数据不足。需要安装 `backend/requirements-ml.txt`。普通历史回填不会被当成当时已经可用的数据。

## 验证

`python backend/scripts/run_checks.py` 使用隔离的数据库路径、清空模型密钥和 SMTP 配置。GitHub Actions 仍用现有 PostgreSQL/pgvector 服务，并自动发现新增测试。本地没有独立的测试 PostgreSQL 时，相关用例显示跳过。
