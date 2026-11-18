import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { SbiStatus } from '../types'

const copy = {
  'zh-CN': { title: 'SBI 导入与净值提醒', disabled: '当前使用持仓快照。设置 SBI_IMPORT_DIR 可开启自动导入。',
    awaiting: '等待账户目录和 config.json。', snapshot: '已核对持仓至', files: '导入记录', valuation: '每万口净值', alerts: '净值提醒',
    compare: '对照 SBI 履历，为每组选择本次新增的成交笔数。已有／导出', additions: '新增笔数', submit: '保存核对结果' },
  en: { title: 'SBI imports and NAV alerts', disabled: 'Showing the holdings snapshot. Set SBI_IMPORT_DIR to enable imports.',
    awaiting: 'Waiting for the account folder and config.json.', snapshot: 'Holdings confirmed through', files: 'Import history', valuation: 'NAV per 10,000 units', alerts: 'NAV alerts',
    compare: 'Check the SBI history and enter the number of new executions per group. Recorded / exported', additions: 'New executions', submit: 'Save reconciliation' },
  ja: { title: 'SBI取込・基準価額アラート', disabled: '保有スナップショットを表示中です。SBI_IMPORT_DIR を設定すると取込が有効になります。',
    awaiting: '口座フォルダーと config.json を待っています。', snapshot: '保有確認日', files: '取込履歴', valuation: '1万口あたりの基準価額', alerts: '基準価額アラート',
    compare: 'SBIの履歴を照合し、グループごとの新規約定件数を入力してください。登録済／出力', additions: '新規約定件数', submit: '照合結果を保存' },
}
type Copy = typeof copy.en

function Reconcile({file, portfolioId, labels}: {file: SbiStatus['files'][number]; portfolioId: string; labels: Copy}) {
  const [values, setValues] = useState<Record<string, number>>({})
  const cache = useQueryClient()
  const mutation = useMutation({mutationFn: () => api.resolveSbiImport(portfolioId, file.id, file.fingerprint!, values),
    onSuccess: () => cache.invalidateQueries({queryKey: ['sbi-status', portfolioId]})})
  if (!file.overlaps || !file.fingerprint) return null
  return <div>
    <p>{labels.compare}</p>
    {file.overlaps.map(row => <p key={row.key}><label>
      {row.date} · {row.symbol} · {row.side} · {row.units} 口 · ¥{row.settlement_jpy} · {row.existing}/{row.exported} · {labels.additions}{' '}
      <input type="number" min={Math.max(0, row.exported - row.existing)} max={row.exported} step={1}
        value={Number.isFinite(values[row.key]) ? values[row.key] : ''}
        onChange={event => setValues(old => ({...old, [row.key]: event.currentTarget.valueAsNumber}))} />
    </label></p>)}
    <button className="secondary-button" disabled={mutation.isPending || file.overlaps.some(row => {
      const count = values[row.key]
      return !Number.isInteger(count) || count < Math.max(0, row.exported - row.existing) || count > row.exported
    })} onClick={() => mutation.mutate()}>{labels.submit}</button>
    {mutation.error && <p role="alert">{mutation.error.message}</p>}
  </div>
}

export function SbiPanel({portfolioId}: {portfolioId: string}) {
  const {i18n} = useTranslation()
  const labels = copy[i18n.resolvedLanguage as keyof typeof copy] ?? copy.en
  const status = useQuery({queryKey: ['sbi-status', portfolioId], queryFn: () => api.sbiStatus(portfolioId), refetchInterval: 15000})
  const data = status.data
  return <section className="panel work-panel sbi-import-status">
    <div className="work-panel-heading"><h2>{labels.title}</h2></div>
    {status.error && <p role="alert">{status.error.message}</p>}
    {data && !data.enabled && <p>{labels.disabled}</p>}
    {data?.enabled && !data.files.length && <p>{labels.awaiting}</p>}
    {data?.snapshot && <p>{labels.snapshot} {data.snapshot.confirmed_through}</p>}
    {Boolean(data?.valuations.length) && <details><summary>{labels.valuation}</summary>
      {data?.valuations.map(row => <p key={row.id}>{row.symbol} · {row.day} · ¥{row.nav}</p>)}
    </details>}
    {Boolean(data?.files.length) && <div><h3>{labels.files}</h3>
      {data?.files.map(file => <div key={file.id}>
        <p>{file.file} · {file.status} {file.rows != null ? `· ${file.rows}` : ''} {file.error}</p>
        {file.status === 'needs_review' && <Reconcile key={file.fingerprint} file={file} portfolioId={portfolioId} labels={labels} />}
      </div>)}
    </div>}
    {Boolean(data?.alerts.length) && <div><h3>{labels.alerts}</h3>
      {data?.alerts.map(alert => <article key={alert.id}><p>{alert.symbol} · {alert.nav_date} · {alert.change_pct}% · {alert.delivery} {alert.error}</p>
        {alert.news.map((doc, index) => <p key={index}>{doc.url && /^https?:\/\//.test(doc.url)
          ? <a href={doc.url} target="_blank" rel="noreferrer">{doc.title}</a> : doc.title}</p>)}
      </article>)}
    </div>}
  </section>
}
