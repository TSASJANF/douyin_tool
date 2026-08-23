import { useEffect, useState } from 'react'
import {
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
  Tabs,
} from 'antd'
import { api } from '../api/client'
import type { AppConfig } from '../types'

const { TextArea } = Input

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
      <Form.Item name={['mimo_api', 'model']} label="模型名称" extra="一般不改">
        <Input />
      </Form.Item>
      <Form.Item
        name={['mimo_api', 'max_completion_tokens']}
        label="最大输出 Token"
        extra="越大能解析越长视频"
      >
        <InputNumber min={1024} step={1024} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={['mimo_api', 'timeout']} label="API 超时(秒)" extra="短视频600，长视频1800">
        <InputNumber min={60} step={60} style={{ width: '100%' }} />
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
      <Form.Item name={['douyin', 'video_quality']} label="视频画质">
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
        extra="短视频2-3，长视频6-10，越高Token消耗越多"
      >
        <InputNumber min={1} max={30} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={['video_analysis', 'media_resolution']} label="分辨率档次">
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

  useEffect(() => {
    api
      .get<{ config: AppConfig }>('/api/config')
      .then((r) => {
        setConfig(r.config)
        form.setFieldsValue(r.config)
      })
      .catch((e) => message.error(`加载配置失败: ${e instanceof Error ? e.message : e}`))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (values: AppConfig) => {
    if (!config) return
    setSaving(true)
    try {
      // 合并保存：保留界面未覆盖的未知字段
      const merged = { ...config, ...values }
      await api.put('/api/config', { config: merged })
      setConfig(merged)
      message.success('配置已保存，对之后创建的任务生效')
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : e}`)
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
