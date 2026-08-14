import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CircleDollarSign, ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { Change, ErrorPanel, LoadingPanel, money, PageHeader } from '../components/UI'
import { formatDateTime } from '../i18n/format'
import type { PaperOrder } from '../types'

export function TradingPage() {
  const { t } = useTranslation(['trading', 'common'])
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
  if (orders.isPending) return <LoadingPanel label={t('trading:loading')} />
  if (orders.error) return <ErrorPanel error={orders.error} />

  return (
    <>
      <PageHeader eyebrow={t('trading:eyebrow')} title={t('trading:title')} description={t('trading:description')} action={<span className="paper-pill">{t('trading:paperOnly')}</span>} />
      <div className="paper-warning"><ShieldCheck />{t('trading:warning')}</div>
      <section className="trading-grid">
        <article className="panel order-ticket">
          <div className="panel-title"><div><span>ORDER TICKET</span><h2>{t('trading:createDraft')}</h2></div></div>
          <div className="segmented"><button className={side === 'buy' ? 'active buy' : ''} onClick={() => setSide('buy')}>{t('common:side.buy')}</button><button className={side === 'sell' ? 'active sell' : ''} onClick={() => setSide('sell')}>{t('common:side.sell')}</button></div>
          <label>{t('trading:symbol')}<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label>
          <label>{t('trading:quantity')}<input type="number" min="0.01" step="0.01" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          <div className="ticket-note"><CircleDollarSign />{t('trading:marketNote')}</div>
          <button className="primary-button full-button" disabled={create.isPending || !symbol || Number(quantity) <= 0} onClick={() => create.mutate()}>{create.isPending ? t('trading:checking') : t('trading:createAndCheck')}</button>
          {create.error && <div className="inline-alert">{create.error.message}</div>}
        </article>

        <article className="panel risk-preview">
          <div className="panel-title"><div><span>RISK GATE</span><h2>{t('trading:preview')}</h2></div></div>
          {!draft ? <div className="empty-risk"><ShieldCheck /><p>{t('trading:previewEmpty')}</p></div> : <>
            <div className="draft-summary"><div><span>{t(`common:side.${draft.side}`)}</span><strong>{draft.quantity} {draft.symbol}</strong></div><div><span>{t('trading:estimated')}</span><strong>{money(draft.estimated_notional)}</strong></div></div>
            <div className={`risk-decision ${draft.risk_result.approved ? 'approved' : 'rejected'}`}>{draft.risk_result.approved ? <ShieldCheck /> : <ShieldX />}<div><strong>{draft.risk_result.approved ? t('trading:approved') : t('trading:rejected')}</strong><span>{draft.risk_result.policy_version}</span></div></div>
            <div className="risk-checks">{draft.risk_result.checks.map((check) => <div key={check.code} className={check.passed ? 'passed' : 'failed'}>{check.passed ? <Check /> : <ShieldX />}<span>{check.message}</span></div>)}</div>
            {draft.status === 'awaiting_confirmation' && <button className="confirm-button" onClick={() => confirm.mutate(draft.id)} disabled={confirm.isPending}>{confirm.isPending ? t('trading:filling') : t('trading:confirm')}</button>}
            {draft.status === 'paper_filled' && <div className="filled-banner"><Check />{t('trading:filled', { price: money(draft.filled_price ?? 0, 'USD', 2) })}</div>}
          </>}
        </article>
      </section>
      <section className="panel">
        <div className="panel-title"><div><span>AUDIT TRAIL</span><h2>{t('trading:orders')}</h2></div></div>
        {orders.data.items.length ? <div className="table-wrap"><table><thead><tr><th>{t('trading:table.time')}</th><th>{t('trading:table.stock')}</th><th>{t('trading:table.side')}</th><th>{t('trading:table.quantity')}</th><th>{t('trading:table.estimated')}</th><th>{t('trading:table.status')}</th></tr></thead><tbody>{orders.data.items.map((order) => <tr key={order.id}><td>{formatDateTime(order.created_at)}</td><td><strong>{order.symbol}</strong></td><td className={order.side === 'buy' ? 'positive' : 'negative'}>{t(`common:side.${order.side}`)}</td><td>{order.quantity}</td><td>{money(order.estimated_notional)}</td><td><span className={`order-status status-${order.status}`}>{t(`common:orderStatus.${order.status}`, { defaultValue: order.status })}</span></td></tr>)}</tbody></table></div> : <div className="empty-table">{t('trading:noOrders')}</div>}
      </section>
    </>
  )
}
