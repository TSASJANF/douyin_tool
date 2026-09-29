import { useEffect, useRef } from 'react'
import { Card, Collapse, Space, Tag, Typography } from 'antd'
import { LoadingOutlined } from '@ant-design/icons'

const { Text } = Typography

interface Props {
  analysis?: { reasoning: string; content: string } | null
  streaming: boolean
}

/**
 * 流式解析面板：
 * - 思考过程默认折叠，点击展开（实时刷新）
 * - 正文实时输出，带闪烁光标；任务完成后由「解析结果」卡片接管展示
 */
export default function AnalysisStream({ analysis, streaming }: Props) {
  const contentRef = useRef<HTMLDivElement>(null)
  const reasoningLen = analysis?.reasoning?.length ?? 0
  const contentLen = analysis?.content?.length ?? 0

  useEffect(() => {
    const el = contentRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [contentLen, reasoningLen])

  if (!analysis || (reasoningLen === 0 && contentLen === 0)) return null

  return (
    <Card
      size="small"
      title="实时解析"
      extra={
        streaming ? (
          <Tag icon={<LoadingOutlined />} color="processing">
            接收中…
          </Tag>
        ) : (
          <Tag color="default">已结束</Tag>
        )
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        {reasoningLen > 0 && (
          <Collapse
            ghost
            size="small"
            defaultActiveKey={[]}
            items={[
              {
                key: 'reasoning',
                label: (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    🧠 思考过程（默认折叠，点击展开，已接收 {reasoningLen} 字）
                  </Text>
                ),
                children: (
                  <div className="stream-box stream-box-reasoning">{analysis.reasoning}</div>
                ),
              },
            ]}
          />
        )}

        {streaming && contentLen > 0 && (
          <>
            <Text type="secondary" style={{ fontSize: 12 }}>
              正文（实时输出，{contentLen} 字）
            </Text>
            <div className="stream-box stream-box-content" ref={contentRef}>
              {analysis.content}
              {streaming && <span className="stream-cursor" />}
            </div>
          </>
        )}
      </Space>
    </Card>
  )
}
