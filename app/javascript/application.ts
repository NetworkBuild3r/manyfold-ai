// Turbo and Stimulus
import '@hotwired/turbo-rails'
import './controllers/index'

import Rails from '@rails/ujs'
import 'masonry-layout'

import 'altcha/external'
import 'altcha/i18n/cs'
import 'altcha/i18n/de'
import 'altcha/i18n/en'
import 'altcha/i18n/es-es'
import 'altcha/i18n/fr-fr'
import 'altcha/i18n/ja'
import 'altcha/i18n/nl'
import 'altcha/i18n/pl'

document.addEventListener('DOMContentLoaded', () => {
  // Legacy Rails UJS
  Rails.start()
})

// Preserve focus across Turbo morph refreshes so form inputs remain usable
let focusedElementBeforeMorph: { id?: string, name?: string, tagName: string } | null = null
document.addEventListener('turbo:before-render', () => {
  const el = document.activeElement as HTMLElement | null
  if (el != null && el.matches('input:not([type="hidden"]), textarea, select')) {
    const inputEl = el as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    const idVal = el.id
    const nameVal = inputEl.name
    focusedElementBeforeMorph = {
      id: (idVal != null && idVal !== '') ? idVal : undefined,
      name: (nameVal != null && nameVal !== '') ? nameVal : undefined,
      tagName: el.tagName
    }
  } else {
    focusedElementBeforeMorph = null
  }
}, { capture: true })
document.addEventListener('turbo:render', (event: Event) => {
  const e = event as CustomEvent<{ renderMethod?: string }>
  if (e.detail?.renderMethod !== 'morph' || (focusedElementBeforeMorph == null)) return
  let target: HTMLElement | null = null
  const idVal = focusedElementBeforeMorph.id
  if (idVal != null && idVal !== '') {
    target = document.getElementById(idVal)
  }
  const nameVal = focusedElementBeforeMorph.name
  if ((target == null) && (nameVal != null && nameVal !== '')) {
    target = document.querySelector(
      `${focusedElementBeforeMorph.tagName.toLowerCase()}[name="${CSS.escape(nameVal)}"]`
    )
  }
  if (target != null && target.matches('input:not([type="hidden"]), textarea, select')) {
    target.focus()
  }
  focusedElementBeforeMorph = null
})
