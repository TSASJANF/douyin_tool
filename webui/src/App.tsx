import { useEffect, useState } from 'react'
import { Layout, Menu } from 'antd'
import { GithubOutlined } from '@ant-design/icons'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import ParsePage from './pages/ParsePage'
import DownloadPage from './pages/DownloadPage'
import ParseOnlyPage from './pages/ParseOnlyPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import { useTaskStore } from './store/taskStore'

const { Sider, Header, Content } = Layout

const menuItems = [
  { key: '/parse', label: '视频解析' },
  { key: '/download', label: '仅下载' },
  { key: '/parse-only', label: '仅解析' },
  { key: '/history', label: '历史记录' },
  { key: '/settings', label: '设置' },
]

const PAGE_META: Record<string, { title: string; desc: string }> = {
  '/parse': { title: '视频解析', desc: '粘贴抖音链接或口令，自动下载并提取视频文案' },
  '/download': { title: '仅下载', desc: '只下载 1080P 视频，不调用解析、不消耗 API 额度' },
  '/parse-only': { title: '仅解析', desc: '本地视频文件或视频直链，直接提取文案' },
  '/history': { title: '历史记录', desc: '浏览已下载视频与解析结果，支持在线播放' },
  '/settings': { title: '设置', desc: '全局参数配置，保存后对后续创建的任务生效' },
}

/** 服务健康状态徽标 */
function HealthBadge() {
  const [ok, setOk] = useState<boolean | null>(null)

  useEffect(() => {
    const check = () =>
      fetch('/api/health')
        .then((r) => setOk(r.ok))
        .catch(() => setOk(false))
    check()
    const timer = setInterval(check, 15000)
    return () => clearInterval(timer)
  }, [])

  return (
    <span className={`health${ok === false ? ' down' : ''}`}>
      <span className="health-dot" />
      {ok === false ? '服务离线' : '服务运行中'}
    </span>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const startPolling = useTaskStore((s) => s.startPolling)

  useEffect(() => {
    startPolling()
  }, [startPolling])

  const meta = PAGE_META[location.pathname] ?? { title: '抖音解析工具', desc: '' }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider className="app-sider" width={200}>
        <div className="brand">
          <div className="brand-name">抖音解析工具</div>
          <div className="brand-sub">视频下载与文案解析</div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
        <a
          className="sider-footer"
          href="https://github.com/TSASJANF/douyin_tool"
          target="_blank"
          rel="noreferrer"
        >
          <GithubOutlined />
          <span>Douyin Tool</span>
        </a>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div className="page-title">{meta.title}</div>
              <div className="page-desc">{meta.desc}</div>
            </div>
            <HealthBadge />
          </div>
        </Header>
        <Content className="app-content">
          <Routes>
            <Route path="/" element={<Navigate to="/parse" replace />} />
            <Route path="/parse" element={<ParsePage />} />
            <Route path="/download" element={<DownloadPage />} />
            <Route path="/parse-only" element={<ParseOnlyPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
