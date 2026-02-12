import { Controller } from '@hotwired/stimulus'

const STORAGE_KEY = 'model_list_selection'

// Connects to data-controller="model-list-selection". Manages selection state for model
// cards (bubbles) and toolbar (Edit single, Bulk edit, Clear). Selection is optional
// persisted to sessionStorage so refresh keeps it; clear on bulk-edit entry or when clearing.
export default class extends Controller {
  static targets = ['bubble', 'toolbar', 'editLink', 'bulkEditForm', 'idsContainer', 'clearButton']

  declare selectedIds: Set<string>
  declare bubbleTargets: HTMLElement[]
  declare hasBubbleTarget: boolean
  declare toolbarTarget: HTMLElement
  declare hasToolbarTarget: boolean
  declare editLinkTarget: HTMLAnchorElement
  declare hasEditLinkTarget: boolean
  declare bulkEditFormTarget: HTMLFormElement
  declare idsContainerTarget: HTMLElement
  declare hasIdsContainerTarget: boolean
  declare clearButtonTarget: HTMLElement

  connect (): void {
    this.selectedIds = new Set(this.loadStored())
    this.syncBubbles()
    this.syncToolbar()
  }

  toggle (event: Event): void {
    event.preventDefault()
    event.stopPropagation()
    const el = event.currentTarget as HTMLElement
    const id = el.dataset.modelId
    if (id == null) return
    if (this.selectedIds.has(id)) {
      this.selectedIds.delete(id)
    } else {
      this.selectedIds.add(id)
    }
    this.persist()
    this.syncBubbles()
    this.syncToolbar()
  }

  clear (): void {
    this.selectedIds.clear()
    this.persist()
    this.syncBubbles()
    this.syncToolbar()
  }

  // Clear selection when user submits the bulk-edit form (navigating to bulk edit page).
  clearOnSubmit (): void {
    this.clear()
  }

  private loadStored (): string[] {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as unknown
        return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
      }
    } catch {
      // ignore
    }
    return []
  }

  private persist (): void {
    try {
      if (this.selectedIds.size > 0) {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...this.selectedIds]))
      } else {
        sessionStorage.removeItem(STORAGE_KEY)
      }
    } catch {
      // ignore
    }
  }

  private syncBubbles (): void {
    if (!this.hasBubbleTarget) return
    this.bubbleTargets.forEach((el) => {
      const id = el.dataset.modelId
      if (id != null && this.selectedIds.has(id)) {
        el.classList.add('model-card-selection-selected')
        el.setAttribute('aria-pressed', 'true')
      } else {
        el.classList.remove('model-card-selection-selected')
        el.setAttribute('aria-pressed', 'false')
      }
    })
  }

  private syncToolbar (): void {
    if (!this.hasToolbarTarget) return
    const count = this.selectedIds.size
    this.toolbarTarget.hidden = count === 0

    if (count > 0) {
      if (this.hasEditLinkTarget) {
        if (count === 1) {
          const id = [...this.selectedIds][0]
          this.editLinkTarget.href = (this.editLinkTarget.dataset.baseHref ?? '').replace('__ID__', id)
          this.editLinkTarget.hidden = false
        } else {
          this.editLinkTarget.hidden = true
        }
      }

      if (this.hasIdsContainerTarget) {
        this.idsContainerTarget.innerHTML = ''
        this.selectedIds.forEach((id) => {
          const input = document.createElement('input')
          input.type = 'hidden'
          input.name = 'ids[]'
          input.value = id
          this.idsContainerTarget.appendChild(input)
        })
      }
    }
  }
}
