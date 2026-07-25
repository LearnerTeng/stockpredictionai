import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CircleDollarSign, ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { Change, ErrorPanel, LoadingPanel, money, PageHeader } from '../components/UI'
import type { PaperOrder } from '../types'

export function TradingPage() {
  const queryClient = useQueryClient()
  const [symbol, setSymbol] = useState('NVDA')
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [quantity, setQuantity] = useState('1')
  const [draft, setDraft] = useState<PaperOrder | null>(null)
  const orders = useQuery({ queryKey: ['orders'], queryFn: api.orders })
  const create = useMutation({
    mutationFn: () => api.createOrder({ symbol, side, quantity: Number(quantity), order_type: 'market' }),
    onSuccess: setDraft,
  })
  const confirm = useMutation({
    mutationFn: (id: string) => api.confirmOrder(id),
    onSuccess: async (order) => {
      setDraft(order)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['orders'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
    },
  })
  if (orders.isPending) return <LoadingPanel label="正在读取模拟订单" />
  if (orders.error) return <ErrorPanel error={orders.error} />

  return (
    <>
      <PageHeader eyebrow="Paper execution desk" title="模拟交易中心" description="AI 只能提出草案；订单必须先经过确定性风险策略，再由你确认。" action={<span className="paper-pill">PAPER ONLY</span>} />
      <div className="paper-warning"><ShieldCheck />当前未连接任何真实券商。所有成交仅更新本地模拟组合，不涉及真实资金。</div>
      <section className="trading-grid">
        <article className="panel order-ticket">
          <div className="panel-title"><div><span>ORDER TICKET</span><h2>创建订单草案</h2></div></div>
          <div className="segmented"><button className={side === 'buy' ? 'active buy' : ''} onClick={() => setSide('buy')}>买入</button><button className={side === 'sell' ? 'active sell' : ''} onClick={() => setSide('sell')}>卖出</button></div>
          <label>股票代码<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label>
          <label>数量<input type="number" min="0.01" step="0.01" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          <div className="ticket-note"><CircleDollarSign />市场单参考价来自组合或推荐快照，确认时后端会再次检查现金和持仓。</div>
          <button className="primary-button full-button" disabled={create.isPending || !symbol || Number(quantity) <= 0} onClick={() => create.mutate()}>{create.isPending ? '风控检查中...' : '生成草案并检查风险'}</button>
          {create.error && <div className="inline-alert">{create.error.message}</div>}
        </article>

        <article className="panel risk-preview">
          <div className="panel-title"><div><span>RISK GATE</span><h2>订单预览</h2></div></div>
          {!draft ? <div className="empty-risk"><ShieldCheck /><p>提交订单草案后，这里将显示逐项风险检查。</p></div> : <>
            <div className="draft-summary"><div><span>{draft.side === 'buy' ? '买入' : '卖出'}</span><strong>{draft.quantity} {draft.symbol}</strong></div><div><span>预计金额</span><strong>{money(draft.estimated_notional)}</strong></div></div>
            <div className={`risk-decision ${draft.risk_result.approved ? 'approved' : 'rejected'}`}>{draft.risk_result.approved ? <ShieldCheck /> : <ShieldX />}<div><strong>{draft.risk_result.approved ? '风险检查通过' : '风险检查拒绝'}</strong><span>{draft.risk_result.policy_version}</span></div></div>
            <div className="risk-checks">{draft.risk_result.checks.map((check) => <div key={check.code} className={check.passed ? 'passed' : 'failed'}>{check.passed ? <Check /> : <ShieldX />}<span>{check.message}</span></div>)}</div>
            {draft.status === 'awaiting_confirmation' && <button className="confirm-button" onClick={() => confirm.mutate(draft.id)} disabled={confirm.isPending}>{confirm.isPending ? '模拟成交中...' : '确认并执行模拟订单'}</button>}
            {draft.status === 'paper_filled' && <div className="filled-banner"><Check />模拟成交完成，成交价 ${draft.filled_price?.toFixed(2)}</div>}
          </>}
        </article>
      </section>
      <section className="panel">
        <div className="panel-title"><div><span>AUDIT TRAIL</span><h2>订单记录</h2></div></div>
        {orders.data.items.length ? <div className="table-wrap"><table><thead><tr><th>时间</th><th>股票</th><th>方向</th><th>数量</th><th>预计金额</th><th>状态</th></tr></thead><tbody>{orders.data.items.map((order) => <tr key={order.id}><td>{new Date(order.created_at).toLocaleString('zh-CN')}</td><td><strong>{order.symbol}</strong></td><td className={order.side === 'buy' ? 'positive' : 'negative'}>{order.side === 'buy' ? '买入' : '卖出'}</td><td>{order.quantity}</td><td>{money(order.estimated_notional)}</td><td><span className={`order-status status-${order.status}`}>{order.status}</span></td></tr>)}</tbody></table></div> : <div className="empty-table">还没有模拟订单</div>}
      </section>
    </>
  )
}
