export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed'
export type TaskMode = 'full' | 'download' | 'parse'
export type ParseSourceType = 'url' | 'file'

export interface Stage {
  index: number
  label: string
}

export interface DownloadProgress {
  percent: number | null
  downloaded_mb: number
  total_mb: number | null
  speed_str: string | null
  eta: string | null
}

export interface TaskResult {
  title: string
  content?: string | null
  output_dir: string
  dir?: string
  files: string[]
}

export interface TaskView {
  id: string
  url: string
  mode: TaskMode
  source_type: ParseSourceType | null
  status: TaskStatus
  title: string
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
  stage: Stage | null
  progress: DownloadProgress | null
}

export interface TaskDetail extends TaskView {
  logs: string[]
  result: TaskResult | null
}

/** 任务级临时参数覆盖（空值=跟随全局配置） */
export interface TaskOverrides {
  fps?: number
  media_resolution?: string
  prompt?: string
}

export interface CreateTaskBody {
  url?: string
  mode: TaskMode
  source_type?: ParseSourceType
  upload_id?: string
  overrides?: TaskOverrides
}

export interface UploadResult {
  upload_id: string
  filename: string
  size: number
}

export interface HistoryFile {
  name: string
  size: number
  mtime: number
}

export interface HistoryItem {
  name: string
  mtime: number
  files: HistoryFile[]
}

export type AppConfig = Record<string, Record<string, unknown>>
