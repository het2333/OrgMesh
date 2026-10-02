/// <reference types="vite/client" />

import type { DesktopApi } from '../shared/ipc'
import type { ProjectApi } from '@genoffice/project-store'

declare global {
  interface Window {
    orgmeshDocs?: {
      mount(host: import('./platform/host').DocsHostPort): Promise<() => void>
      save(): Promise<boolean>
      hasUnsavedChanges(): boolean
      getSnapshot(): import('./platform/host').DocumentSnapshot | null
    }
    desktop: DesktopApi
    projectApi: ProjectApi
  }
}

export {}
