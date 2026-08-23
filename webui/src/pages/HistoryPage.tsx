import { useEffect, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Empty,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { api, fileDownloadUrl, fileStreamUrl } from '../api/client'
import type { HistoryItem } from '../types'

const { Text } = Typography

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

const isVideo = (name: string) => /\.(mp4|mkv|mov|webm|avi)$/i.test(name)

export default function HistoryPage() {
  const { message } = App.useApp()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState<HistoryItem | null>(null)
  const [textContent, setTextContent] = useState<string | null>(null)
  const [textLoading, setTextLoading] = useState(false)
  const [playing, setPlaying] = useState<{ dir: string; file: string } | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await api.get<HistoryItem[]>('/api/history'))
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openDetail = (item: HistoryItem) => {
    setCurrent(item)
    setTextContent(null)
    setOpen(true)
    loadText(item, '正文.txt')
  }

  const loadText = async (item: HistoryItem, file: string) => {
    if (!item.files.some((f) => f.name === file)) {
      setTextContent('（无正文文件）')
      return
    }
    setTextLoading(true)
    try {
      const resp = await api.get<{ name: string; content: string }>(
        `/api/history/content?dir=${encodeURIComponent(item.name)}&file=${encodeURIComponent(file)}`,
      )
      setTextContent(resp.content)
    } catch {
      setTextContent('（读取失败）')
    } finally {
      setTextLoading(false)
    }
  }

  return (
    <div>
      <Table<HistoryItem>
        rowKey="name"
        loading={loading}
        dataSource={items}
        locale={{ emptyText: <Empty description="暂无历史记录，去解析一个视频吧" /> }}
        columns={[
          { title: '标题', dataIndex: 'name', ellipsis: true },
          {
            title: '时间',
            dataIndex: 'mtime',
            width: 180,
            render: (v: number) => new Date(v * 1000).toLocaleString(),
          },
          { title: '文件数', dataIndex: 'files', width: 90, render: (f: HistoryItem['files']) => f.length },
          {
            title: '操作',
            width: 120,
            render: (_, item) => (
              <Button type="link" size="small" onClick={() => openDetail(item)}>
                查看详情
              </Button>
            ),
          },
        ]}
        title={() => (
          <Space>
            <span style={{ fontWeight: 600 }}>历史记录</span>
            <Typography.Link onClick={load}>刷新</Typography.Link>
          </Space>
        )}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />

      <Drawer
        title={current?.name}
        width={680}
        open={open}
        onClose={() => setOpen(false)}
        destroyOnClose
      >
        {current && (
          <Tabs
            items={[
              {
                key: 'files',
                label: '文件',
                children: (
                  <Table
                    rowKey="name"
                    size="small"
                    dataSource={current.files}
                    pagination={false}
                    columns={[
                      { title: '文件名', dataIndex: 'name', ellipsis: true },
                      {
                        title: '大小',
                        dataIndex: 'size',
                        width: 100,
                        render: (v: number) => formatSize(v),
                      },
                      {
                        title: '操作',
                        width: 150,
                        render: (_, f) => (
                          <Space size={4}>
                            {isVideo(f.name) && (
                              <Button
                                type="link"
                                size="small"
                                onClick={() => setPlaying({ dir: current.name, file: f.name })}
                              >
                                播放
                              </Button>
                            )}
                            <Button
                              type="link"
                              size="small"
                              href={fileDownloadUrl(current.name, f.name)}
                            >
                              下载
                            </Button>
                          </Space>
                        ),
                      },
                    ]}
                  />
                ),
              },
              {
                key: 'content',
                label: '正文',
                children: (
                  <div className="content-box" style={{ minHeight: 120 }}>
                    {textLoading ? '加载中…' : textContent || '（无正文文件）'}
                  </div>
                ),
              },
              {
                key: 'info',
                label: '信息',
                children: <InfoTab dir={current.name} files={current.files} />,
              },
            ]}
          />
        )}
      </Drawer>

      <Modal
        open={!!playing}
        title={playing?.file}
        footer={null}
        width={860}
        destroyOnClose
        onCancel={() => setPlaying(null)}
      >
        {playing && (
          <video
            controls
            autoPlay
            style={{ width: '100%', maxHeight: '70vh' }}
            src={fileStreamUrl(playing.dir, playing.file)}
          />
        )}
      </Modal>
    </div>
  )
}

/** info.txt 解析为键值对展示 */
function InfoTab({ dir, files }: { dir: string; files: HistoryItem['files'] }) {
  const [lines, setLines] = useState<string[] | null>(null)

  useEffect(() => {
    if (!files.some((f) => f.name === 'info.txt')) {
      setLines([])
      return
    }
    api
      .get<{ content: string }>(
        `/api/history/content?dir=${encodeURIComponent(dir)}&file=${encodeURIComponent('info.txt')}`,
      )
      .then((r) => setLines(r.content.split('\n').filter((l) => l.trim())))
      .catch(() => setLines([]))
  }, [dir, files])

  if (lines === null) return <Text type="secondary">加载中…</Text>
  if (lines.length === 0) return <Text type="secondary">（无信息文件）</Text>

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 16px' }}>
      {lines.map((line, i) => {
        const idx = line.indexOf(': ')
        if (idx > 0) {
          return (
            <div key={i} style={{ display: 'contents' }}>
              <Text type="secondary">{line.slice(0, idx)}</Text>
              <Text copyable={{ text: line.slice(idx + 2) }}>{line.slice(idx + 2)}</Text>
            </div>
          )
        }
        return (
          <div key={i} style={{ gridColumn: '1 / -1' }}>
            <Tag>{line}</Tag>
          </div>
        )
      })}
    </div>
  )
}
