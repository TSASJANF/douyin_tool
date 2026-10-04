import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Input, Row, Space, Typography } from 'antd'
import TaskListCard from '../components/TaskListCard'
import TaskPanel from '../components/TaskPanel'
import { useTaskStore } from '../store/taskStore'

const { TextArea } = Input
const { Text } = Typography

/** 仅下载页：只下载视频，不做 MiMo 解析（抖音/视频号自动识别） */
export default function DownloadPage() {
  const { message } = App.useApp()
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { createTask, fetchTasks } = useTaskStore()

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const submit = async () => {
    const text = url.trim()
    if (!text) {
      message.warning('请输入抖音/视频号链接或分享口令')
      return
    }
    setSubmitting(true)
    try {
      await createTask({ url: text, mode: 'download' })
      setUrl('')
      message.success('下载任务已创建')
    } catch (e) {
      message.error(`创建失败: ${e instanceof Error ? e.message : e}`, 8)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Row gutter={16}>
      <Col xs={24} lg={9} xl={7}>
        <Card title="新建下载任务" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            <Text type="secondary">
              仅下载视频（抖音保留 1080P，视频号保留原画），不调用 MiMo 解析，不消耗 API 额度。
            </Text>
            <TextArea
              rows={3}
              placeholder={'粘贴抖音链接/口令，或视频号分享链接，例如：\n7.89 复制打开抖音 https://v.douyin.com/xxxxxx/ ...\nhttps://weixin.qq.com/sph/xxxxxx'}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <Button type="primary" loading={submitting} onClick={submit} block>
              开始下载
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
