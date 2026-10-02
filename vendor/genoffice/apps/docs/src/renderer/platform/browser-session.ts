interface BrowserSession {
  save(): Promise<boolean>
  hasChanges(): boolean
}
let session: BrowserSession | null = null

export function bindBrowserSession(value: BrowserSession): () => void {
  session = value
  return () => {
    if (session === value) session = null
  }
}
export function hasBrowserChanges(): boolean {
  return session?.hasChanges() ?? false
}
export async function saveBrowserDocument(): Promise<boolean> {
  return session?.save() ?? false
}
