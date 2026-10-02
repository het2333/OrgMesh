import { createRoot } from 'react-dom/client'
import { htmlLang, normalizeLang } from '@genoffice/i18n'
import { installScreenTips } from '@genoffice/ui'
import { App } from './App'
import { hasBrowserChanges, saveBrowserDocument } from './platform/browser-session'
import { createHttpDocsHost } from './platform/http-host'
import { LocaleProvider, setModuleLang } from './i18n/locale'
import { installDocsHost, getHostedSnapshot, type DocsHostPort } from './platform/host'
import '@genoffice/ui/tokens.css'
import '@genoffice/ui/screentip.css'
import '@genoffice/ui/color-picker.css'
import '@genoffice/ui/dropdown.css'
import '@genoffice/ui/ribbon-collapse.css'
import '@genoffice/ui/markdown.css'
import '@genoffice/ui/ai-panel-prefs.css'
import '@genoffice/ui/ai-scope-quote.css'
import '@genoffice/ui/image-viewer.css'
import './styles.css'
import './fonts/fonts.css'

export async function mountDocs(host: DocsHostPort): Promise<() => void> {
  const container = document.getElementById('root')
  if (!container) throw new Error('DOCS_ROOT_REQUIRED')
  const disposeHost = installDocsHost(host)
  const language = host.language ?? 'en'
  setModuleLang(language)
  document.documentElement.lang = htmlLang(language)
  installScreenTips()
  const root = createRoot(container)
  root.render(
    <LocaleProvider initial={language}>
      <App />
    </LocaleProvider>,
  )
  return () => {
    root.unmount()
    disposeHost()
  }
}

// The same-origin embedding shell passes its bounded host; no credentials cross windows.
window.orgmeshDocs = Object.freeze({
  mount: mountDocs,
  save: saveBrowserDocument,
  hasUnsavedChanges: hasBrowserChanges,
  getSnapshot: getHostedSnapshot,
})

const params = new URLSearchParams(window.location.search)
const documentId = params.get('document_id')
if (documentId) {
  void mountDocs(createHttpDocsHost(documentId, normalizeLang(params.get('lang'))))
}
