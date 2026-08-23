# v2 修改记录（备用，以后上传GitHub时参考）

## 新增功能

### 1. 配置引导程序 (setup.py)
- 首次运行自动引导配置所有参数
- 包括MiMo API、OneDrive、视频解析、阈值等
- 支持高级参数配置

### 2. OneDrive可选功能
- config.json 中添加 `onedrive.enabled` 字段，默认为 `true`
- 引导程序中询问是否启用OneDrive
- 禁用后遇到大文件提示用户手动输入直链

### 3. OneDrive配置引导修复
- 显示详细的Azure应用创建指南
- 包含"允许公共客户端流"步骤

### 4. 主程序更新
- 首次运行自动启动配置向导
- 根据 `onedrive.enabled` 选择处理方式
- OneDrive禁用时提示用户手动输入直链

## 文件结构

```
douyin_tool_v2/
├── main.py           # 主程序（新增首次运行引导）
├── setup.py          # 配置引导程序（新增）
├── config.json       # 配置文件（新增onedrive.enabled）
├── requirements.txt
├── README.md
└── modules/
    ├── __init__.py
    ├── douyin_downloader.py
    ├── video_analyzer.py
    ├── onedrive_handler.py
    └── clash_manager.py
```

## config.json 新增字段

```json
{
  "onedrive": {
    "enabled": true  // 新增：是否启用OneDrive功能
  }
}
```
