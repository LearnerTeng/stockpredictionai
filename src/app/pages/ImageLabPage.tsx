import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileImage, ScanSearch, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, API_BASE } from '../api'
import { PageHeader } from '../components/UI'

export function ImageLabPage() {
  const { t } = useTranslation('imageLab')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [algorithm, setAlgorithm] = useState('baseline-inspector')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const client = useQueryClient()
  const history = useQuery({ queryKey: ['image-history', page], queryFn: () => api.imageHistory(page) })
  const detail = useQuery({ queryKey: ['image-job', selected], queryFn: () => api.imageJob(selected!), enabled: !!selected })
  const analyze = useMutation({ mutationFn: () => api.analyzeImage(file!, algorithm),
    onSuccess: () => client.invalidateQueries({ queryKey: ['image-history'] }) })
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  const choose = (selected: File | null) => {
    if (preview) URL.revokeObjectURL(preview)
    setFile(selected)
    setPreview(selected ? URL.createObjectURL(selected) : null)
    analyze.reset()
  }

  return (
    <>
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} action={<a className="secondary-button" href="#image-history" onClick={event => { event.preventDefault(); document.getElementById('image-history')?.scrollIntoView() }}>{t('history')}</a>} />
      <section className="image-lab-grid">
        <article className="panel upload-panel">
          <select aria-label={t('algorithm')} value={algorithm} onChange={e => setAlgorithm(e.target.value)}>
            <option value="baseline-inspector">Baseline Inspector</option><option value="chart-vision-lite">Chart Vision Lite</option><option value="edge-focus">Edge Focus</option>
          </select>
          <label className="drop-zone"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => choose(event.target.files?.[0] ?? null)} />{preview ? <img src={preview} alt={t('previewAlt')} /> : <><Upload /><strong>{t('choose')}</strong><span>{t('chooseHint')}</span></>}</label>
          <button className="primary-button full-button" disabled={!file || analyze.isPending} onClick={() => analyze.mutate()}><ScanSearch size={17} />{analyze.isPending ? t('analyzing') : t('analyze')}</button>
          {analyze.error && <div className="inline-alert">{analyze.error.message}</div>}
        </article>
        <article className="panel image-result">
          <div className="panel-title"><div><span>STRUCTURED OUTPUT</span><h2>{t('result')}</h2></div></div>
          {analyze.data ? <pre>{JSON.stringify(analyze.data, null, 2)}</pre> : <div className="empty-risk"><FileImage /><p>{t('empty')}</p></div>}
        </article>
      </section>
      <section id="image-history" className="panel">
        <h2>{t('history')}</h2>
        {history.error && <div className="inline-alert">{history.error.message}</div>}
        {history.isPending && <p>{t('loadingHistory')}</p>}
        {history.data?.items.length === 0 && <p>{t('emptyHistory')}</p>}
        <div className="image-lab-grid">{history.data?.items.map(job => <article key={job.id}>
          <button className="secondary-button" onClick={() => setSelected(job.id)}>{new Date(job.created_at).toLocaleString()} · {job.algorithm} · {job.status}</button>
          {job.output_url && <a href={`${API_BASE}${job.output_url}`} target="_blank" rel="noreferrer"><img style={{ maxWidth: '100%' }} src={`${API_BASE}${job.output_url}`} alt={job.summary ?? job.algorithm} /></a>}
          <p>{job.summary}</p>
        </article>)}</div>
        <button disabled={page === 1} onClick={() => setPage(page-1)}>{t('previous')}</button>
        <span> {page} </span><button disabled={!history.data || history.data.items.length < 8} onClick={() => setPage(page+1)}>{t('next')}</button>
        {detail.error && <div className="inline-alert">{detail.error.message}</div>}
        {detail.data && <pre style={{ overflow: 'auto' }}>{JSON.stringify(detail.data, null, 2)}</pre>}
      </section>
    </>
  )
}
