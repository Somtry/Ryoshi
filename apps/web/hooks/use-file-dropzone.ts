import { useCallback, useState } from 'react'

import { toast } from 'sonner'

import { getAccessToken } from '@/lib/api-client'
import { UploadedFile } from '@/lib/types'

type UseFileDropzoneProps = {
  uploadedFiles: UploadedFile[]
  setUploadedFiles: React.Dispatch<React.SetStateAction<UploadedFile[]>>
  maxFiles?: number
  allowedTypes?: string[]
  chatId: string
}

export function useFileDropzone({
  uploadedFiles,
  setUploadedFiles,
  chatId,
  maxFiles = 3,
  allowedTypes = ['image/png', 'image/jpeg', 'application/pdf']
}: UseFileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false)
    }
  }, [])

  const handleDrop = useCallback(
    async (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragging(false)

      const rawFiles = Array.from(e.dataTransfer.files)

      const allowed = rawFiles.filter(file => allowedTypes.includes(file.type))
      const rejected = rawFiles.filter(file => !allowed.includes(file))

      if (rejected.length > 0) {
        toast.error(
          'Some files were not accepted: ' +
            rejected.map(f => f.name).join(', ')
        )
      }

      const total = uploadedFiles.length + allowed.length
      if (total > maxFiles) {
        toast.error(`You can upload a maximum of ${maxFiles} files.`)
        return
      }

      const initialFiles: UploadedFile[] = allowed.map(file => ({
        file,
        status: 'uploading'
      }))

      setUploadedFiles(prev => [...prev, ...initialFiles].slice(0, maxFiles))

      await Promise.all(
        initialFiles.map(async uf => {
          const formData = new FormData()
          formData.append('file', uf.file!)
          formData.append('chatId', chatId)

          try {
            // FormData 不能走 apiFetch(会强制 JSON Content-Type 破坏 boundary),
            // 手动附加 Authorization 头,登录用户上传的文件才能归属其账号
            const token = getAccessToken()
            const res = await fetch('/api/upload', {
              method: 'POST',
              body: formData,
              credentials: 'include',
              headers: token ? { Authorization: `Bearer ${token}` } : undefined
            })

            if (!res.ok) throw new Error('Upload failed')

            const { file: uploaded } = await res.json()

            setUploadedFiles(prev =>
              prev.map(f =>
                f.file === uf.file
                  ? {
                      ...f,
                      status: 'uploaded',
                      url: uploaded.url,
                      name: uploaded.filename,
                      key: uploaded.key,
                      mediaType: uploaded.mediaType,
                      libraryFileId: uploaded.id
                    }
                  : f
              )
            )
          } catch (err) {
            toast.error(`Failed to upload ${uf.file?.name ?? 'file'}`)
            setUploadedFiles(prev =>
              prev.map(f =>
                f.file === uf.file ? { ...f, status: 'error' } : f
              )
            )
          }
        })
      )
    },
    [allowedTypes, maxFiles, uploadedFiles, setUploadedFiles, chatId]
  )

  return {
    isDragging,
    handleDragOver,
    handleDragLeave,
    handleDrop
  }
}
