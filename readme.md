# TradingAI

用于行情观察、量化研究、新闻情绪分析和模拟交易的本地工作台。
React + TypeScript 前端、Flask API、SQLAlchemy/PostgreSQL 数据层，以及可选图像服务。

本项目不是实盘交易系统。默认账户含演示数据，预测不构成收益承诺；LLM 解释与确定性交易风控分离。

## 启动

需要 Node.js、Python 3.11+；推荐 PostgreSQL。命令从仓库根目录运行。

```powershell
npm ci
python -m pip install -r backend/requirements.txt
# 可选：训练和加载梯度提升模型
python -m pip install -r backend/requirements-ml.txt
```

根据 `backend/.env.example` 创建本地 `backend/.env`。使用 PostgreSQL 时先启动数据库，再执行
`python -m alembic upgrade head`。未配置 `DATABASE_URL` 时保留旧 SQLite 兼容模式，但它不提供新的版本化行情和执行账本。

分别在不同终端运行：

```powershell
python backend/app.py
npm run dev
```

打开 <http://localhost:5173>。图像功能另需运行
`python -m uvicorn backend.image_service.main:app --host 127.0.0.1 --port 8001`。

## 已实现的研究基础

- 美股 5/20 交易日相对 SPY 的预测目标、时间顺序验证、模型归档与显式降级。
- 行情追加版本、可用时间与入库时间查询、证券身份/代码有效期/历史成分导入；回填不会伪装成当年已知数据。
- 多资产、次日成交的 USD 美股组合回测，包含现金、手续费、滑点、成交量约束和显式公司行动。
- 已归档预测的滚动前向评分、非重叠样本统计，以及可选的退化模型停用。
- 模拟交易的事务性成交/现金账本和对账命令；风险页展示历史 VaR、ES、Beta。
- React 单入口、ECharts 图表和图像历史浏览。

新能力的命令、数据格式与限制见 [量化基础操作说明](docs/quant-platform.md)。
完整部署、新闻工作进程和 API 说明见 [开发指南](DEVELOPMENT.md)。

## 验证

```powershell
python backend/scripts/run_checks.py
npm run typecheck
npm run build
```

测试脚本隔离本地账户、数据库与模型目录；PostgreSQL 集成测试需单独设置专用 `TEST_POSTGRES_URL`，否则跳过。
原始 GAN 教学 notebook 仍作为历史研究资料保留，不代表当前在线模型架构。
