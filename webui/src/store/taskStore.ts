import { create } from 'zustand'
import { api, wsUrl } from '../api/client'
import type { CreateTaskBody, TaskDetail, TaskView } from '../types'

const MAX_LOGS = 500

interface TaskState {
  tasks: TaskView[]
  currentId: string | null
  detail: TaskDetail | null
  polling: boolean
  fetchTasks: () => Promise<void>
  createTask: (body: CreateTaskBody) => Promise<string>
  selectTask: (id: string) => Promise<void>
  startPolling: () => void
  stopPolling: () => void
}

let pollTimer: ReturnType<typeof setInterval> | null = null
let activeWs: WebSocket | null = null

function closeActiveWs() {
  if (activeWs) {
    activeWs.onclose = null
    activeWs.close()
    activeWs = null
  }
}

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: [],
  currentId: null,
  detail: null,
  polling: false,

  fetchTasks: async () => {
    try {
      const tasks = await api.get<TaskView[]>('/api/tasks')
      const { currentId, detail } = get()
      set({ tasks })
      // 同步当前任务的摘要状态（WS 断开时的兜底）
      if (currentId && detail) {
        const summary = tasks.find((t) => t.id === currentId)
        if (summary && summary.status !== detail.status) {
          set({ detail: { ...detail, status: summary.status, stage: summary.stage, progress: summary.progress, error: summary.error, title: summary.title } })
          if (summary.status === 'completed' || summary.status === 'failed') {
            get().selectTask(currentId)
          }
        }
      }
    } catch {
      /* 后端不可达时静默，轮询下一轮重试 */
    }
  },

  createTask: async (body: CreateTaskBody) => {
    const task = await api.post<TaskView>('/api/tasks', body)
    await get().fetchTasks()
    get().selectTask(task.id)
    return task.id
  },

  selectTask: async (id: string) => {
    closeActiveWs()
    set({ currentId: id })
    try {
      const detail = await api.get<TaskDetail>(`/api/tasks/${id}`)
      set({ detail })
    } catch {
      set({ detail: null })
      return
    }
    const current = get().detail
    if (current && (current.status === 'pending' || current.status === 'running')) {
      connectWs(id, set, get)
    }
  },

  startPolling: () => {
    if (pollTimer) return
    set({ polling: true })
    pollTimer = setInterval(() => get().fetchTasks(), 3000)
  },

  stopPolling: () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    set({ polling: false })
  },
}))

type SetState = (partial: Partial<TaskState>) => void
type GetState = () => TaskState

function connectWs(taskId: string, set: SetState, get: GetState) {
  closeActiveWs()
  const ws = new WebSocket(wsUrl(taskId))
  activeWs = ws

  ws.onmessage = (ev) => {
    if (get().currentId !== taskId) return
    let msg: { type: string; data: unknown }
    try {
      msg = JSON.parse(ev.data as string)
    } catch {
      return
    }
    const detail = get().detail
    if (!detail) return

    switch (msg.type) {
      case 'snapshot': {
        set({ detail: msg.data as TaskDetail })
        const snap = msg.data as TaskDetail
        if (snap.status === 'completed' || snap.status === 'failed') closeActiveWs()
        break
      }
      case 'stage':
        set({ detail: { ...detail, stage: msg.data as TaskDetail['stage'] } })
        break
      case 'download_progress':
        set({ detail: { ...detail, progress: msg.data as TaskDetail['progress'] } })
        break
      case 'analysis_delta': {
        // 流式解析增量：reasoning=思考过程，content=正文
        const d = msg.data as { reasoning?: string; content?: string }
        const cur = detail.analysis ?? { reasoning: '', content: '' }
        set({
          detail: {
            ...detail,
            analysis: {
              reasoning: cur.reasoning + (d.reasoning ?? ''),
              content: cur.content + (d.content ?? ''),
            },
          },
        })
        break
      }
      case 'log': {
        const text = (msg.data as { text: string }).text
        const logs = [...detail.logs, text].slice(-MAX_LOGS)
        set({ detail: { ...detail, logs } })
        break
      }
      case 'done': {
        const payload = msg.data as TaskDetail['result']
        set({
          detail: {
            ...detail,
            status: 'completed',
            result: payload,
            title: payload?.title ?? detail.title,
          },
        })
        break
      }
      case 'error': {
        const message = (msg.data as { message: string }).message
        set({ detail: { ...detail, status: 'failed', error: message } })
        break
      }
      case 'task_status': {
        const status = (msg.data as { status: string }).status
        set({ detail: { ...detail, status: status as TaskDetail['status'] } })
        closeActiveWs()
        get().fetchTasks()
        break
      }
    }
  }

  ws.onclose = () => {
    if (activeWs === ws) activeWs = null
    // 非终态断开时兜底：拉取详情刷新状态
    const d = get().detail
    if (get().currentId === taskId && d && (d.status === 'running' || d.status === 'pending')) {
      setTimeout(() => {
        if (get().currentId === taskId) get().selectTask(taskId)
      }, 1500)
    }
  }
}
