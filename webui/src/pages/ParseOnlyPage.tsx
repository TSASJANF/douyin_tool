import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Input, Row, Segmented, Space, Typography, Upload } from 'antd'
import type { UploadProps } from 'antd'
import OverridePanel from '../components/OverridePanel'
import TaskListCard from '../components/TaskListCard'
import TaskPanel from '../components/TaskPanel'
import { useTaskStore } from '../store/taskStore'
import type { ParseSourceType, TaskOverrides, UploadResult } from '../types'

const { Text } = Typography

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024).toFixed(0)} KB`
}

/** 通过 XHR 原始流上传（大文件不占用前端内存），带进度回调 */
function putUpload(file: File, onProgress: (percent: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `/api/uploads?filename=${encodeURIComponent(file.name)}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResult)
        } catch {
          reject(new Error('服务端响应异常'))
        }
      } else {
        let detail = `HTTP ${xhr.status}`
        try {
          const body = JSON.parse(xhr.responseText)
          if (body?.detail) detail = body.detail
        } catch {
          /* ignore */
        }
        reject(new Error(`上传失败: ${detail}`))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误，上传中断'))
    xhr.send(file)
  })
}

/** 仅解析页：本地文件或视频直链 → MiMo 解析（不下载抖音视频） */
export default function ParseOnlyPage() {
  const { message } = App.useApp()
  const [sourceType, setSourceType] = useState<ParseSourceType>('file')
  const [url, setUrl] = useState('')
  const [upload, setUpload] = useState<UploadResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [overrides, setOverrides] = useState<TaskOverrides>({})
  const [submitting, setSubmitting] = useState(false)
  const { createTask, fetchTasks } = useTaskStore()

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const uploadProps: UploadProps = {
    multiple: false,
    maxCount: 1,
    accept: 'video/*,.mp4,.mkv,.mov,.avi,.wmv,.webm,.flv,.ts',
    customRequest: (options) => {
      const file = options.file as File
      setUploading(true)
      putUpload(file, (percent) => options.onProgress?.({ percent } as never))
        .then((res) => {
          setUpload(res)
          options.onSuccess?.(res)
          message.success(`已上传 ${res.filename}（${formatSize(res.size)}）`)
        })
        .catch((e: Error) => {
          options.onError?.(e as never)
          message.error(e.message, 8)
        })
        .finally(() => setUploading(false))
    },
    onRemove: () => {
      setUpload(null)
      message.info('已移除，请重新选择文件')
    },
  }

  const ready = sourceType === 'file' ? !!upload : !!url.trim()

  const submit = async () => {
    if (sourceType === 'file' && !upload) {
      message.warning('请先选择并上传本地视频文件')
      return
    }
    if (sourceType === 'url' && !url.trim()) {
      message.warning('请输入视频直链')
      return
    }
    setSubmitting(true)
    try {
      await createTask({
        mode: 'parse',
        source_type: sourceType,
        url: sourceType === 'url' ? url.trim() : undefined,
        upload_id: sourceType === 'file' ? upload!.upload_id : undefined,
        overrides: Object.keys(overrides).length ? overrides : undefined,
      })
      message.success('解析任务已创建')
    } catch (e) {
      message.error(`创建失败: ${e instanceof Error ? e.message : e}`, 8)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Row gutter={16}>
      <Col xs={24} lg={9} xl={7}>
        <Card title="新建解析任务" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            <Text type="secondary">
              选择本地视频文件或粘贴视频直链，直接送 MiMo 解析（不经过抖音下载）。
            </Text>

            <Segmented
              block
              value={sourceType}
              onChange={(v) => setSourceType(v as ParseSourceType)}
              options={[
                { value: 'file', label: '本地文件' },
                { value: 'url', label: '视频直链' },
              ]}
            />

            {sourceType === 'file' ? (
              <Upload.Dragger {...uploadProps} disabled={uploading}>
                <p className="ant-upload-text" style={{ fontSize: 14 }}>
                  点击或拖拽视频文件到此处上传
                </p>
                <p className="ant-upload-hint">支持 mp4 / mkv / mov 等格式，上传后保存在服务端</p>
              </Upload.Dragger>
            ) : (
              <Input
                placeholder="https://.../video.mp4（可播放的视频直链）"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            )}

            <OverridePanel value={overrides} onChange={setOverrides} />

            <Button type="primary" loading={submitting} disabled={!ready} onClick={submit} block>
              开始解析
            </Button>
          </Space>
        </Card>

        <TaskListCard />
      </Col>

      <Col xs={24} lg={15} xl={17}>
        <TaskPanel />
      </Col>
    </Row>
  )
}
