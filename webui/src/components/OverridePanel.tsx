import { useEffect, useState } from 'react'
import { Collapse, Input, InputNumber, Select, Space, Typography } from 'antd'
import { api } from '../api/client'
import type { AppConfig, TaskOverrides } from '../types'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  value: TaskOverrides
  onChange: (value: TaskOverrides) => void
}

/**
 * 任务级临时解析参数面板（默认折叠）。
 * 留空的项跟随全局配置；填写的项仅对本次提交的任务生效，不修改 config.json。
 */
export default function OverridePanel({ value, onChange }: Props) {
  const [global, setGlobal] = useState<{ fps?: number; media_resolution?: string; prompt?: string }>({})

  useEffect(() => {
    api
      .get<{ config: AppConfig }>('/api/config')
      .then((r) => {
        const va = (r.config.video_analysis ?? {}) as Record<string, unknown>
        setGlobal({
          fps: va.fps as number | undefined,
          media_resolution: va.media_resolution as string | undefined,
          prompt: va.prompt as string | undefined,
        })
      })
      .catch(() => {
        /* 占位信息缺失不影响功能 */
      })
  }, [])

  const promptPlaceholder = global.prompt
    ? `跟随全局：${global.prompt.length > 60 ? global.prompt.slice(0, 60) + '…' : global.prompt}`
    : '跟随全局设置'

  return (
    <Collapse
      ghost
      size="small"
      items={[
        {
          key: 'overrides',
          label: '临时解析参数（仅本次任务生效，点击展开）',
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              <Space wrap size="middle">
                <div>
                  <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                    抽帧率（全局: {global.fps ?? '-'}）
                  </Text>
                  <InputNumber
                    min={1}
                    max={30}
                    value={value.fps ?? null}
                    placeholder="跟随全局"
                    style={{ width: 120 }}
                    onChange={(v) => onChange({ ...value, fps: v ?? undefined })}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                    分辨率（全局: {global.media_resolution ?? '-'}）
                  </Text>
                  <Select
                    allowClear
                    value={value.media_resolution}
                    placeholder="跟随全局"
                    style={{ width: 140 }}
                    options={[
                      { value: 'default', label: 'default（平衡）' },
                      { value: 'max', label: 'max（最高）' },
                    ]}
                    onChange={(v) => onChange({ ...value, media_resolution: v ?? undefined })}
                  />
                </div>
              </Space>
              <div>
                <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                  分析提示词
                </Text>
                <TextArea
                  rows={3}
                  value={value.prompt ?? ''}
                  placeholder={promptPlaceholder}
                  onChange={(e) => onChange({ ...value, prompt: e.target.value || undefined })}
                />
              </div>
            </Space>
          ),
        },
      ]}
    />
  )
}
