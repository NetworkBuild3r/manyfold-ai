import { Controller } from '@hotwired/stimulus'

/**
 * Abstract base for selection controllers that manage bubble + toolbar state
 * with sessionStorage persistence. Subclasses define storage key, data attribute
 * for item id, and selected CSS class; they implement syncToolbar() for
 * controller-specific toolbar behavior.
 */
export default abstract class BaseSelectionController extends Controller {
  static targets = ['bubble', 'toolbar']

  declare selectedIds: Set<string>
  declare bubbleTargets: HTMLElement[]
  declare hasBubbleTarget: boolean
  declare toolbarTarget: HTMLElement
  declare hasToolbarTarget: boolean

  abstract get storageKey (): string
  abstract get idDataAttribute (): string
  abstract get selectedClass (): string

  connect (): void {
    this.selectedIds = new Set(this.loadStored())
    this.syncBubbles()
    this.syncToolbar()
  }

  toggle (event: Event): void {
    event.preventDefault()
    event.stopPropagation()
    const el = event.currentTarget as HTMLElement
    const id = el.dataset[this.idDataAttribute as keyof DOMStringMap]
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

  clearOnSubmit (): void {
    this.clear()
  }

  protected loadStored (): string[] {
    try {
      const raw = sessionStorage.getItem(this.storageKey)
      if (raw) {
        const parsed = JSON.parse(raw) as unknown
        return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
      }
    } catch {
      // ignore
    }
    return []
  }

  protected persist (): void {
    try {
      if (this.selectedIds.size > 0) {
        sessionStorage.setItem(this.storageKey, JSON.stringify([...this.selectedIds]))
      } else {
        sessionStorage.removeItem(this.storageKey)
      }
    } catch {
      // ignore
    }
  }

  protected syncBubbles (): void {
    if (!this.hasBubbleTarget) return
    const key = this.idDataAttribute as keyof DOMStringMap
    this.bubbleTargets.forEach((el) => {
      const id = el.dataset[key]
      if (id != null && this.selectedIds.has(id)) {
        el.classList.add(this.selectedClass)
        el.setAttribute('aria-pressed', 'true')
      } else {
        el.classList.remove(this.selectedClass)
        el.setAttribute('aria-pressed', 'false')
      }
    })
  }

  protected get hasSelectedOnPage (): boolean {
    if (!this.hasBubbleTarget) return false
    const key = this.idDataAttribute as keyof DOMStringMap
    return this.bubbleTargets.some(
      (el) => (el.dataset[key]) != null && this.selectedIds.has(el.dataset[key])
    )
  }

  abstract syncToolbar (): void
}
