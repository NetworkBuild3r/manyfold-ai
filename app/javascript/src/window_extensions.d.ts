import type { Application } from '@hotwired/stimulus'

declare global {
  interface Window {
    i18n: { t: (key: string) => string, locale: string }
    Stimulus: Application
  }
}

export {}
