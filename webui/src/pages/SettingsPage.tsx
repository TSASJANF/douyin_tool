import { useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
} from 'antd'
import { api } from '../api/client'
import type { AppConfig } from '../types'

const { TextArea } = Input

/** MiMo 可用模型（官方文档「模型列表」，模型名必须全小写） */
const MODEL_OPTIONS = [
  { value: 'mimo-v2.6-pro', label: 'mimo-v2.6-pro（推荐，旗舰）' },
  { value: 'mimo-v2.6-flash', label: 'mimo-v2.6-flash（高并发场景）' },
  { value: 'mimo-v2.6-pro-ultraspeed', label: 'mimo-v2.6-pro-ultraspeed（超高速）' },
  { value: 'mimo-v2.5', label: 'mimo-v2.5（即将于 2026-10-21 下线）' },
]

/** 模型输出 Token 硬上限（官方文档：v2.5/v2.6 全系最大输出 128K） */
const MAX_COMPLETION_TOKENS = 131072

/** 各分组的表单字段定义 */
function MiMoForm() {
  return (
    <>
      <Form.Item name={['mimo_api', 'api_key']} label="API Key" rules={[{ required: true, message: '必填' }]}>
        <Input.Password placeholder="MiMo API Key（https://platform.xiaomimimo.com/console）" />
      </Form.Item>
      <Form.Item name={['mimo_api', 'base_url']} label="API 地址" extra="一般不改">
        <Input />
      </Form.Item>
      <Form.Item
        name={['mimo_api', 'model']}
        label="模型名称"
        extra="必须全小写；可下拉选择，也可手动输入其他模型名"
        rules={[{ required: true, message: '必填' }]}
      >
        {/* tags 模式：既能从下拉选，也允许手动输入自定义模型名（上限 1 个） */}
        <Select
          mode="tags"
          maxCount={1}
          options={MODEL_OPTIONS}
          placeholder="选择或输入模型名，如 mimo-v2.6-pro"
        />
      </Form.Item>
      <Form.Item
        name={['mimo_api', 'max_completion_tokens']}
        label="最大输出 Token"
        extra={`模型硬上限 ${MAX_COMPLETION_TOKENS}（128K），超出会被 API 直接拒绝(400)；越大能解析越长视频`}
        rules={[
          { required: true, message: '必填' },
          {
            type: 'number',
            min: 1,
            max: MAX_COMPLETION_TOKENS,
            message: `必须在 1~${MAX_COMPLETION_TOKENS} 之间（模型硬上限 128K）`,
          },
        ]}
      >
        <InputNumber min={1} max={MAX_COMPLETION_TOKENS} step={1024} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item
        name={['mimo_api', 'deep_thinking']}
        label="深度思考"
        extra="提取逐字稿建议关闭：v2.6 系列开启后可能把整篇结果写进思考过程导致正文为空（工具会自动关闭思考重试兜底）；开启更慢、更耗 Token"
        valuePropName="checked"
      >
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item
        name={['mimo_api', 'timeout']}
        label="API 超时(秒)"
        extra="短视频600，长视频1800；最大输出Token越大、解析越久"
        rules={[
          { required: true, message: '必填' },
          { type: 'number', min: 60, max: 3600, message: '必须在 60~3600 秒之间' },
        ]}
      >
        <InputNumber min={60} max={3600} step={60} style={{ width: '100%' }} />
      </Form.Item>
    </>
  )
}

function DouyinForm() {
  return (
    <>
      <Form.Item name={['douyin', 'download_dir']} label="下载目录" extra="相对于程序目录">
        <Input />
      </Form.Item>
      <Form.Item name={['douyin', 'max_retry']} label="下载重试次数">
        <InputNumber min={0} max={10} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={['douyin', 'video_quality']} label="视频画质" extra="当前实际固定下载1080P">
        <Select
          options={[
            { value: 'highest', label: 'highest（最高）' },
            { value: '1080p', label: '1080p' },
            { value: '720p', label: '720p' },
          ]}
        />
      </Form.Item>
    </>
  )
}

function AnalysisForm() {
  return (
    <>
      <Form.Item
        name={['video_analysis', 'fps']}
        label="抽帧率(帧/秒)"
        extra="文档范围 0.1~10（默认2）；短视频2-3，长视频6-10，越高Token消耗越多"
        rules={[
          { required: true, message: '必填' },
          { type: 'number', min: 0.1, max: 10, message: '必须在 0.1~10 之间（文档允许范围）' },
        ]}
      >
        <InputNumber min={0.1} max={10} step={0.1} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item
        name={['video_analysis', 'media_resolution']}
        label="分辨率档次"
        rules={[{ required: true, message: '必填' }]}
      >
        <Select
          options={[
            { value: 'default', label: 'default（平衡）' },
            { value: 'max', label: 'max（最高）' },
          ]}
        />
      </Form.Item>
      <Form.Item
        name={['video_analysis', 'prompt']}
        label="分析提示词"
        extra="控制文案提取方式，可自定义"
        rules={[{ required: true, message: '必填' }]}
      >
        <TextArea rows={5} />
      </Form.Item>
    </>
  )
}

export default function SettingsPage() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<{ config: AppConfig }>('/api/config')
      .then((r) => {
        setConfig(r.config)
        form.setFieldsValue(r.config)
      })
      .catch((e) => message.error(`加载配置失败: ${e instanceof Error ? e.message : e}`, 8))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (values: AppConfig) => {
    if (!config) return
    setSaving(true)
    setSaveError(null)
    try {
      // 合并保存：保留界面未覆盖的未知字段
      const merged = { ...config, ...values }
      await api.put('/api/config', { config: merged })
      setConfig(merged)
      message.success('配置已保存，对之后创建的任务生效')
    } catch (e) {
      // 服务端会返回具体原因（哪个字段、当前值、合法范围），原样展示，不让用户猜
      const text = e instanceof Error ? e.message : String(e)
      setSaveError(text)
      message.error(`保存失败: ${text}`, 12)
    } finally {
      setSaving(false)
    }
  }

  if (!config) {
    return (
      <Card>
        <Spin tip="加载配置中…" style={{ display: 'block', margin: '80px auto' }} />
      </Card>
    )
  }

  return (
    <Card title="配置管理" style={{ maxWidth: 860 }}>
      <Form form={form} layout="vertical" onFinish={save}>
        <Tabs
          items={[
            { key: 'mimo', label: 'MiMo API', children: <MiMoForm /> },
            { key: 'douyin', label: '抖音下载', children: <DouyinForm /> },
            { key: 'analysis', label: '视频解析', children: <AnalysisForm /> },
          ]}
        />
        {saveError && (
          <Alert
            type="error"
            showIcon
            closable
            onClose={() => setSaveError(null)}
            message="配置未保存，请按以下提示修正"
            description={saveError}
            style={{ marginTop: 8, marginBottom: 8 }}
          />
        )}
        <Space style={{ marginTop: 8 }}>
          <Popconfirm
            title="确认保存配置？"
            description="将写入 config.json（原文件备份为 config.json.bak）"
            onConfirm={() => form.submit()}
          >
            <Button type="primary" htmlType="submit" loading={saving}>
              保存配置
            </Button>
          </Popconfirm>
          <Button onClick={() => form.setFieldsValue(config)}>重置</Button>
        </Space>
      </Form>
    </Card>
  )
}
