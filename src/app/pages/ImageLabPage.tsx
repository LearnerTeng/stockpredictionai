import { useMutation } from '@tanstack/react-query'
import { FileImage, ScanSearch, Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { PageHeader } from '../components/UI'

export function ImageLabPage() {
  const { t } = useTranslation('imageLab')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const analyze = useMutation({ mutationFn: () => api.analyzeImage(file!) })
  const choose = (selected: File | null) => {
    if (preview) URL.revokeObjectURL(preview)
    setFile(selected)
    setPreview(selected ? URL.createObjectURL(selected) : null)
    analyze.reset()
  }

  return (
    <>
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} action={<a className="secondary-button" href="/image-lab.html">{t('history')}</a>} />
      <section className="image-lab-grid">
        <article className="panel upload-panel">
          <label className="drop-zone"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => choose(event.target.files?.[0] ?? null)} />{preview ? <img src={preview} alt={t('previewAlt')} /> : <><Upload /><strong>{t('choose')}</strong><span>{t('chooseHint')}</span></>}</label>
          <button className="primary-button full-button" disabled={!file || analyze.isPending} onClick={() => analyze.mutate()}><ScanSearch size={17} />{analyze.isPending ? t('analyzing') : t('analyze')}</button>
          {analyze.error && <div className="inline-alert">{analyze.error.message}</div>}
        </article>
        <article className="panel image-result">
          <div className="panel-title"><div><span>STRUCTURED OUTPUT</span><h2>{t('result')}</h2></div></div>
          {analyze.data ? <pre>{JSON.stringify(analyze.data, null, 2)}</pre> : <div className="empty-risk"><FileImage /><p>{t('empty')}</p></div>}
        </article>
      </section>
    </>
  )
}
