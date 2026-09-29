import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Progress,
  Space,
  Steps,
  Tag,
  Typography,
} from 'antd'
import { fileDownloadUrl, fileStreamUrl } from '../api/client'
import { useTaskStore } from '../store/taskStore'
import { statusTag } from './TaskListCard'
import AnalysisStream from './AnalysisStream'
import type { TaskMode } from '../types'

const { Text } = Typography

const STAGE_TITLES: Record<TaskMode, string[]> = {
  full: ['解析链接并下载1080P视频', '获取720P直链', '解析视频内容'],
  download: ['解析链接并下载1080P视频'],
  parse: ['解析视频内容'],
}

/** 当前任务详情面板：步骤条 + 下载进度 + 日志 + 结果（三种任务模式共用） */
export default function TaskPanel() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const { detail } = useTaskStore()
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [detail?.logs?.length])

  if (!detail) {
    return (
      <Card>
        <Empty description="选择或创建一个任务开始" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    )
  }

  const mode: TaskMode = detail.mode ?? 'full'
  const titles = STAGE_TITLES[mode]
  const currentStage = detail.stage?.index ?? 0
  const stepStatus =
    detail.status === 'failed' ? 'error' : detail.status === 'completed' ? 'finish' : 'process'

  const result = detail.result
  const resultDir =
    result?.dir || (result?.output_dir ? result.output_dir.split(/[\\/]/).pop() || '' : '')
  const videoFile = result?.files.find((f) => /\.(mp4|mkv|mov|webm)$/i.test(f))

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Card title="任务进度" extra={statusTag(detail.status)} size="small">
        <Steps
          size="small"
          current={Math.min(Math.max(currentStage - 1, 0), titles.length - 1)}
          status={stepStatus === 'error' ? 'error' : undefined}
          items={titles.map((label, i) => ({
            title: label,
            description:
              detail.status === 'failed' && currentStage === i + 1 ? '在此步骤失败' : undefined,
          }))}
          style={{ marginBottom: 8, marginTop: 4 }}
        />

        {/* 下载进度 */}
        {detail.stage?.index === 1 && detail.progress && detail.status === 'running' && (
          <div style={{ marginTop: 16 }}>
            {detail.progress.percent != null ? (
              <Progress percent={Math.round(detail.progress.percent)} status="active" />
            ) : (
              <Progress percent={99} status="active" />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              {detail.progress.downloaded_mb?.toFixed(1)} MB
              {detail.progress.total_mb ? ` / ${detail.progress.total_mb.toFixed(1)} MB` : ''}
              {detail.progress.speed_str ? ` · 速度 ${detail.progress.speed_str}` : ''}
              {detail.progress.eta ? ` · 剩余 ${detail.progress.eta}` : ''}
            </Text>
          </div>
        )}

        {detail.status === 'pending' && (
          <Text type="secondary">排队等待中（同时最多处理 2 个任务）…</Text>
        )}

        {detail.status === 'failed' && detail.error && (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            message="任务失败（具体原因如下）"
            description={
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <div style={{ whiteSpace: 'pre-wrap' }}>{detail.error}</div>
                <Button
                  size="small"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(detail.error || '')
                      message.success('错误信息已复制，便于反馈排查')
                    } catch {
                      message.error('复制失败，请手动选择复制')
                    }
                  }}
                >
                  复制错误信息
                </Button>
              </Space>
            }
          />
        )}
      </Card>

      {/* 流式解析：思考过程（默认折叠）+ 正文实时输出 */}
      <AnalysisStream
        analysis={detail.analysis}
        streaming={detail.status === 'running' || detail.status === 'pending'}
      />

      {/* 运行日志 */}
      <div className="log-box log-box-bottom" ref={logRef}>
        {detail.logs.length === 0 ? (
          <Text type="secondary">暂无日志</Text>
        ) : (
          detail.logs.map((line, i) => <div key={i}>{line}</div>)
        )}
      </div>

      {/* 结果 */}
      {detail.status === 'completed' && result && (
        <Card
          title={mode === 'download' ? '下载结果' : '解析结果（视频文案）'}
          size="small"
          extra={
            <Space>
              {result.content && (
                <>
                  <Button
                    size="small"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(result.content || '')
                        message.success('已复制到剪贴板')
                      } catch {
                        message.error('复制失败，请手动选择复制')
                      }
                    }}
                  >
                    复制全文
                  </Button>
                  {resultDir && (
                    <Button size="small" href={fileDownloadUrl(resultDir, '正文.txt')}>
                      下载正文
                    </Button>
                  )}
                </>
              )}
            </Space>
          }
        >
          {result.content ? (
            <>
              <div className="content-box">{result.content}</div>
            </>
          ) : (            <Alert
              type="success"
              showIcon
              message="视频下载完成，未做解析"
              description={
                videoFile && resultDir
                  ? '可在下方查看文件，或到「历史记录」页在线播放。'
                  : '可在下方查看文件。'
              }
            />
          )}
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              输出目录：{result.output_dir}
            </Text>
            <br />
            <Space size={[8, 8]} wrap style={{ marginTop: 8 }}>
              {result.files.map((f) => (
                <Tag key={f}>{f}</Tag>
              ))}
            </Space>
            {videoFile && resultDir && (
              <div style={{ marginTop: 8 }}>
                {resultDir.startsWith('_uploads') ? (
                  <Typography.Link href={fileStreamUrl(resultDir, videoFile)} target="_blank">
                    在线播放 {videoFile}
                  </Typography.Link>
                ) : (
                  <Typography.Link onClick={() => navigate('/history')}>
                    前往历史记录播放 {videoFile}
                  </Typography.Link>
                )}
              </div>
            )}
          </div>
        </Card>
      )}
    </Space>
  )
}
