import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Input, Row, Space } from 'antd'
import OverridePanel from '../components/OverridePanel'
import TaskListCard from '../components/TaskListCard'
import TaskPanel from '../components/TaskPanel'
import { useTaskStore } from '../store/taskStore'
import type { TaskOverrides } from '../types'

const { TextArea } = Input

/** 视频解析页：粘贴抖音链接 → 下载 + 解析全流程 */
export default function ParsePage() {
  const { message } = App.useApp()
  const [url, setUrl] = useState('')
  const [overrides, setOverrides] = useState<TaskOverrides>({})
  const [submitting, setSubmitting] = useState(false)
  const { createTask, fetchTasks } = useTaskStore()

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const submit = async () => {
    const text = url.trim()
    if (!text) {
      message.warning('请输入抖音链接或分享口令')
      return
    }
    setSubmitting(true)
    try {
      await createTask({
        url: text,
        mode: 'full',
        overrides: Object.keys(overrides).length ? overrides : undefined,
      })
      setUrl('')
      message.success('任务已创建')
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
            <TextArea
              rows={3}
              placeholder={'粘贴抖音链接或分享口令，例如：\n7.89 复制打开抖音 https://v.douyin.com/xxxxxx/ ...'}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <OverridePanel value={overrides} onChange={setOverrides} />
            <Button type="primary" loading={submitting} onClick={submit} block>
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
