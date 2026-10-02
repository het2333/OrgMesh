import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface PrintWindow {
  loadFile(path: string): Promise<void>
  webContents: {
    executeJavaScript(script: string, userGesture?: boolean): Promise<unknown>
    print(
      options: { silent: boolean; printBackground: boolean },
      callback: (success: boolean, failureReason: string) => void,
    ): void
  }
  show(): void
  focus(): void
  isDestroyed(): boolean
  destroy(): void
}

/** Print from a temporary file so large decks do not exceed Chromium's data-URL limit. */
export async function printSlidesHtml(
  html: string,
  win: PrintWindow,
  platform: NodeJS.Platform = process.platform,
): Promise<{ ok: boolean; error?: string }> {
  let tempDir: string | null = null
  try {
    tempDir = await mkdtemp(join(tmpdir(), 'genoffice-slides-print-'))
    const htmlPath = join(tempDir, 'slides.html')
    await writeFile(htmlPath, html, 'utf8')
    await win.loadFile(htmlPath)
    await win.webContents.executeJavaScript(
      'Promise.all([document.fonts.ready, ...Array.from(document.images).map((i) => i.decode().catch(() => {}))])',
      true,
    )
    // Windows attaches the native dialog to the printed window, which must be visible.
    if (platform === 'win32') {
      win.show()
      win.focus()
    }
    const result = await new Promise<{ success: boolean; failureReason: string }>((resolve) => {
      win.webContents.print({ silent: false, printBackground: true }, (success, failureReason) =>
        resolve({ success, failureReason }),
      )
    })
    if (!result.success) {
      // Canceling keeps the renderer's print dialog and its chosen options open.
      if (result.failureReason === 'Print job canceled') return { ok: false }
      return { ok: false, error: result.failureReason }
    }
    return { ok: true }
  } catch (err) {
    return { ok: false, error: String(err) }
  } finally {
    try {
      if (!win.isDestroyed()) win.destroy()
    } finally {
      if (tempDir) await rm(tempDir, { recursive: true, force: true })
    }
  }
}
