import { useMutation } from '@tanstack/react-query'
import { FileImage, ScanSearch, Upload } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { PageHeader } from '../components/UI'

export function ImageLabPage() {
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
      <PageHeader eyebrow="Computer vision workspace" title="Image Lab" description="上传走势图或其他图片，调用独立 FastAPI 图片算法服务执行同步分析。" action={<a className="secondary-button" href="/image-lab.html">打开完整任务历史</a>} />
      <section className="image-lab-grid">
        <article className="panel upload-panel">
          <label className="drop-zone"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => choose(event.target.files?.[0] ?? null)} />{preview ? <img src={preview} alt="上传预览" /> : <><Upload /><strong>选择 PNG / JPG / WebP 图片</strong><span>点击选择文件，最大限制由后端统一校验</span></>}</label>
          <button className="primary-button full-button" disabled={!file || analyze.isPending} onClick={() => analyze.mutate()}><ScanSearch size={17} />{analyze.isPending ? '算法分析中...' : '开始同步分析'}</button>
          {analyze.error && <div className="inline-alert">{analyze.error.message}</div>}
        </article>
        <article className="panel image-result">
          <div className="panel-title"><div><span>STRUCTURED OUTPUT</span><h2>算法结果</h2></div></div>
          {analyze.data ? <pre>{JSON.stringify(analyze.data, null, 2)}</pre> : <div className="empty-risk"><FileImage /><p>分析后的尺寸、亮度、色彩摘要和结果图信息会显示在这里。</p></div>}
        </article>
      </section>
    </>
  )
}
