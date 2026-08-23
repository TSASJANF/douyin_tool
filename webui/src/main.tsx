import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import type { ThemeConfig } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

/**
 * 设计语言：中性黑白灰，近黑主色，细边框，无装饰渐变。
 * 语义色（成功/处理中/失败）保持 antd 默认。
 */
const INK = '#18181B'

const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: INK,
    colorLink: '#2563EB',
    colorBgLayout: '#F6F6F7',
    borderRadius: 8,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: {
      siderBg: '#FFFFFF',
      headerBg: 'rgba(255,255,255,0.82)',
      headerHeight: 64,
      headerPadding: '0 28px',
    },
    Menu: {
      itemColor: '#52525B',
      itemHoverColor: INK,
      itemSelectedColor: INK,
      itemSelectedBg: '#F4F4F5',
      itemBorderRadius: 8,
      itemMarginInline: 10,
      itemHeight: 38,
      activeBarBorderWidth: 0,
    },
    Card: {
      borderRadiusLG: 12,
      colorBorderSecondary: '#E4E4E7',
      headerFontSize: 14,
    },
    Button: {
      controlHeight: 40,
      fontWeight: 500,
      primaryShadow: '0 1px 2px rgba(0,0,0,0.12)',
    },
    Table: {
      headerBg: 'transparent',
      rowHoverBg: '#FAFAFA',
    },
    Segmented: {
      trackBg: '#F4F4F5',
      itemSelectedBg: '#FFFFFF',
    },
  },
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntApp>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
)
