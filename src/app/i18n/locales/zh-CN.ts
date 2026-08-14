export const zhCN = {
  common: {
    brand: { subtitle: '专业工作台' },
    nav: { dashboard: '总览', monitor: '股票监测', portfolio: '我的组合', assistant: 'AI 助手', trading: '模拟交易', imageLab: '图像实验室' },
    paperMode: '模拟盘', apiGateway: 'API 网关', dataMode: '数据模式', language: '语言',
    searchPlaceholder: '搜索股票代码，例如 NVDA', openMenu: '打开菜单', closeMenu: '关闭菜单',
    loading: '正在读取数据', loadingWorkspace: '正在加载工作台模块', openingAiList: '正在打开 AI 建议列表',
    errorTitle: '数据暂时不可用', errorHint: '请确认 Python 网关已在 8000 端口启动。', invalidResponse: '接口 {{path}} 返回了无效数据', requestFailed: '接口请求失败 ({{status}})',
    updatedAt: '更新时间 {{value}}', demoData: '演示数据', recommendationScore: '推荐度',
    actions: { save: '保存', saving: '保存中...', cancel: '取消', close: '关闭', edit: '编辑', search: '检索', add: '添加', refresh: '刷新' },
    market: { all: '全部市场', US: '美股', JP: '日股', HK: '港股' },
    status: { holding: '已持有', wanted: '想买入', ai_suggested: 'AI 建议', monitoring: '监测中' },
    side: { buy: '买入', sell: '卖出' },
    orderStatus: { awaiting_confirmation: '等待确认', paper_filled: '模拟成交', risk_rejected: '风险拒绝' },
  },
  dashboard: {
    loading: '正在加载投资组合', eyebrow: '投资组合指挥中心', title: '早上好，这是你的市场驾驶舱', description: '推荐来自确定性评分模型，AI 负责解释；所有交易均处于模拟盘。', enterMonitor: '进入股票监测',
    totalEquity: '组合总资产', cashAndPositions: '现金 {{cash}} · 持仓 {{positions}}', periodReturn: '区间收益', aheadOfSpy: '领先 SPY', topPick: '首选股票', topPickDetail: '推荐度 {{score}} · 预期 {{return}}%', noRecommendation: '暂无推荐', riskPosture: '风险姿态', balanced: '均衡', concentrated: '偏满仓', riskLimits: '单笔上限 $10,000 · 单股上限 25%',
    performance: '我的收益 vs 市场', viewPortfolio: '查看组合', todaysRecommendations: '今日推荐', all: '全部', positions: '当前持仓', paperTrade: '模拟交易',
    table: { stock: '股票', quantity: '数量', cost: '成本', price: '现价', marketValue: '市值', weight: '持仓占比', pnl: '浮动盈亏' },
  },
  portfolio: {
    loading: '正在计算组合收益', eyebrow: '投资组合分析', title: '我的投资组合', description: '持仓、现金、资产配置与基准收益集中展示。', paperPortfolio: '模拟投资组合',
    equity: '净资产', marketValue: '持仓市值', cash: '可用现金', unrealizedPnl: '未实现盈亏', allocation: '资产配置', equityCurve: '资产曲线', positions: '持仓明细',
    table: { stock: '股票', quantity: '数量', averageCost: '平均成本', referencePrice: '参考价格', marketValue: '市值', weight: '权重', pnl: '盈亏' },
  },
  trading: {
    loading: '正在读取模拟订单', eyebrow: '模拟执行工作台', title: '模拟交易中心', description: 'AI 只能提出草案；订单必须先经过确定性风险策略，再由你确认。', paperOnly: '仅限模拟', warning: '当前未连接任何真实券商。所有成交仅更新本地模拟组合，不涉及真实资金。',
    createDraft: '创建订单草案', symbol: '股票代码', quantity: '数量', marketNote: '市场单参考价来自组合或推荐快照，确认时后端会再次检查现金和持仓。', checking: '风控检查中...', createAndCheck: '生成草案并检查风险', preview: '订单预览', previewEmpty: '提交订单草案后，这里将显示逐项风险检查。', estimated: '预计金额', approved: '风险检查通过', rejected: '风险检查拒绝', filling: '模拟成交中...', confirm: '确认并执行模拟订单', filled: '模拟成交完成，成交价 {{price}}', orders: '订单记录', noOrders: '还没有模拟订单',
    table: { time: '时间', stock: '股票', side: '方向', quantity: '数量', estimated: '预计金额', status: '状态' },
  },
  assistant: {
    eyebrow: '模型解读', title: 'AI 分析助手', description: '先运行数值预测，再由 AI 解释模型形态、误差与风险；不会生成自动交易指令。', boundaries: '分析边界', dataOnlyTitle: '仅使用后端预测数据', dataOnlyText: '不虚构新闻、财报或实时行情', noOrdersTitle: '不直接给出买卖指令', noOrdersText: '订单必须经过独立风控与确认', fallbackTitle: '本地降级可用', fallbackText: '未配置 OpenAI Key 时返回规则解释', symbol: '股票代码', running: '预测与分析中...', generate: '生成模型解读', process: '分析过程会调用 `/predict`，随后把结构化预测传给 `/ai/analyze`。', waitingTitle: '等待分析任务', waitingText: '输入已导入历史数据的股票代码，系统将生成可审计的模型解释。',
  },
  charts: { portfolioValue: '组合市值', myReturn: '我的收益', benchmark: 'SPY 基准', cash: '现金', pnl: '盈亏 %', positionValue: '持仓市值', noBars: '暂无本地行情', noBarsHint: '先在股票监测页面导入该股票的历史数据。', openMonitor: '打开股票监测' },
  imageLab: { eyebrow: '计算机视觉工作台', title: '图像实验室', description: '上传走势图或其他图片，调用独立 FastAPI 图片算法服务执行同步分析。', history: '打开完整任务历史', previewAlt: '上传预览', choose: '选择 PNG / JPG / WebP 图片', chooseHint: '点击选择文件，最大限制由后端统一校验', analyzing: '算法分析中...', analyze: '开始同步分析', result: '算法结果', empty: '分析后的尺寸、亮度、色彩摘要和结果图信息会显示在这里。' },
  stock: {
    back: '返回监测列表', loading: '正在读取 {{symbol}}', waitingScore: '等待评分', noThesis: '该股票尚未生成 AI 推荐评分。刷新行情后可重新计算监测信号。', description: '单股监控、模型预测、手动买入模拟和 AI 建议买点收益在同一画面完成。', referencePrice: '参考价格', chartTitle: 'K 线监控与预测投影', chartHint: '实线为实际行情，右侧为模型投影', attention: { high: '高关注', positive: '积极观察', neutral: '中性观察' }, factors: { trend: '趋势', fundamental: '基本面', model: '模型', market: '市场', risk: '风险' }, predictionStatus: '预测状态', calculating: '计算中', failed: '失败', steps: '{{count}} 步', predictionEnd: '预测末端', simulationTitle: '输入模拟买入参数', simulating: '模拟中...', runSimulation: '运行收益模拟', quantity: '数量', entryPrice: '买入价', defaultPrice: '默认 {{price}}', forecastDays: '预测交易日', aiEntry: 'AI 建议买点', waitingTitle: '等待模拟参数', waitingText: '输入数量和可选买入价后，系统会生成手动买入与 AI 建议买入时点两套 K 线收益路径。', manualEntry: '手动买入模拟', aiTiming: 'AI 建议时点模拟', entryDate: '买入日', returnRate: '收益率', maxDrawdown: '最大回撤', table: { date: '日期', close: '收盘', value: '市值', pnl: '盈亏', type: '类型' }, projected: '预测', actual: '实际' },
  monitor: {
    eyebrow: '市场监测', title: '股票监测与预测', description: '按市场、持有状态和模型信号检索股票，进入单股画面查看 K 线、预测与模拟收益。', addStock: '添加股票', views: { all: '全部', wanted: '想买入', holding: '已持有', ai: 'AI 建议' },
    editor: { addEyebrow: '加入监测', editEyebrow: '编辑元数据', addTitle: '添加监测股票', editTitle: '编辑股票资料', market: '市场', symbol: '股票代码', name: '名称', namePlaceholder: '自动获取，可手工覆盖', exchange: '交易所', sector: '行业', sectorPlaceholder: '例如：半导体、汽车、互联网', note: '日股代码自动补 .T，港股代码自动补足四位并添加 .HK。行情为延迟日线数据。', save: '保存资料', addAndFetch: '添加并拉取行情' },
    searchPlaceholder: '股票代码或名称', advanced: '高级筛选', filters: { sector: '行业', allSectors: '全部行业', exchange: '交易所', allExchanges: '全部交易所', minPrice: '最低价格', maxPrice: '最高价格', minScore: '最低 AI 分数', maxScore: '最高 AI 分数', direction: '预测方向', all: '全部', up: '预测上涨', down: '预测下跌', freshness: '数据新鲜度', within24h: '24 小时内', within3d: '3 天内', within7d: '7 天内', stale: '超过 7 天或无数据', clear: '清空高级条件' },
    refreshing: '刷新中', refreshCurrent: '刷新当前结果', scheduledRefresh: '定时刷新', minutes: '{{count}} 分钟', custom: '自定义', minuteUnit: '分钟', currentScope: '仅更新当前筛选结果', addedWithWarnings: '股票已加入，但部分远程数据未取得：{{warnings}}', saved: '股票资料已保存。', refreshPartial: '{{success}} 只刷新成功，{{failed}} 只失败。', refreshDone: '{{count}} 只股票刷新完成。', resultCount: '{{count}} 只股票符合条件', reading: '读取中',
    table: { stock: '股票', marketStatus: '市场 / 状态', latestPrice: '最新价', dayChange: '日涨跌', aiScore: 'AI 分数', projectedReturn: '预测收益', holdingPnl: '持仓盈亏', quoteUpdated: '行情 / 更新', actions: '操作' },
    noQuote: '无行情', neverRefreshed: '尚未刷新', removeWanted: '移出想买入', addWanted: '加入想买入', editMetadata: '编辑资料', empty: '没有符合条件的股票，请调整筛选条件或添加监测股票。', previous: '上一页', next: '下一页', page: '第 {{page}} / {{pages}} 页', disclaimer: '行情来自 Yahoo 延迟日线数据；AI 分数和预测用于研究与模拟，不构成投资建议。',
  },
  recommendations: { loading: '正在计算推荐列表', eyebrow: '确定性模型候选', title: 'AI 推荐股票', description: '推荐度由趋势、模型、市场和风险因子组成，LLM 不参与评分计算。', refreshing: '刷新中', refresh: '刷新行情评分', refreshFailed: '刷新失败：{{message}}', sort: '按推荐度排序', expected: '模型预期', mainRisk: '主要风险', view: '查看完整分析', disclaimer: '演示与研究用途，不构成投资建议。刷新功能依赖 Yahoo 行情网络连接，基本面因子在未接入财报源前保持中性值。', factors: { trend: '趋势', fundamental: '基本面', model: '模型', market: '市场', risk: '风险调整' } },
} as const
