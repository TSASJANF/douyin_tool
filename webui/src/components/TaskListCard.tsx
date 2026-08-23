import { Card, Empty, List, Tag, Typography } from 'antd'
import { useTaskStore } from '../store/taskStore'
import type { TaskMode, TaskStatus, TaskView } from '../types'

const MODE_LABEL: Record<TaskMode, { text: string }> = {
  full: { text: '全流程' },
  download: { text: '仅下载' },
  parse: { text: '仅解析' },
}

const STATUS_LABEL: Record<TaskStatus, { text: string; color: string }> = {
  pending: { text: '等待中', color: 'default' },
  running: { text: '进行中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  failed: { text: '失败', color: 'error' },
}

export function statusTag(status: TaskStatus) {
  const { color, text } = STATUS_LABEL[status]
  return <Tag color={color} style={{ marginInlineEnd: 0 }}>{text}</Tag>
}

export default function TaskListCard() {
  const { tasks, currentId, selectTask, fetchTasks } = useTaskStore()

  return (
    <Card
      title="任务列表"
      size="small"
      extra={<Typography.Link onClick={() => fetchTasks()}>刷新</Typography.Link>}
    >
      {tasks.length === 0 ? (
        <Empty description="暂无任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          split={false}
          dataSource={tasks}
          renderItem={(t: TaskView) => (
            <div
              className={`task-item${t.id === currentId ? ' active' : ''}`}
              style={{ cursor: 'pointer' }}
              onClick={() => selectTask(t.id)}
            >
              <List.Item
                style={{ padding: 0, border: 'none' }}
                actions={[statusTag(t.status)]}
              >
                <List.Item.Meta
                  title={
                    <Typography.Text strong={t.id === currentId} ellipsis style={{ maxWidth: 140 }}>
                      {t.title || t.url}
                    </Typography.Text>
                  }
                  description={
                    <span style={{ fontSize: 12 }}>
                      <Tag style={{ marginRight: 4, fontSize: 11, lineHeight: '16px' }}>
                        {MODE_LABEL[t.mode]?.text ?? t.mode}
                      </Tag>
                      {new Date(t.created_at * 1000).toLocaleString()}
                    </span>
                  }
                />
              </List.Item>
            </div>
          )}
        />
      )}
    </Card>
  )
}
