import { Controller } from '@hotwired/stimulus'

// Replaces Bootstrap collapse JS. Toggles visibility by adding/removing the "show" class
// so Bootstrap CSS (e.g. .collapse.show) continues to work.
// Connects to data-controller="collapse". Requires data-collapse-target="content" on the collapsible element.
export default class extends Controller {
  static targets = ['content']

  declare contentTarget: HTMLElement
  declare hasContentTarget: boolean

  toggle (event?: Event): void {
    if (event != null) event.preventDefault()
    if (this.hasContentTarget) {
      this.contentTarget.classList.toggle('show')
      this.syncAriaExpanded()
    }
  }

  show (event?: Event): void {
    if (event != null) event.preventDefault()
    if (this.hasContentTarget) {
      this.contentTarget.classList.add('show')
      this.syncAriaExpanded()
    }
  }

  hide (event?: Event): void {
    if (event != null) event.preventDefault()
    if (this.hasContentTarget) {
      this.contentTarget.classList.remove('show')
      this.syncAriaExpanded()
    }
  }

  // Hide the content target that contains the event target (e.g. the row containing the clicked link).
  hideContaining (event: Event): void {
    event.preventDefault()
    const contained = (event.target as Element)?.closest?.('[data-collapse-target="content"]')
    if (contained != null) {
      contained.classList.remove('show')
    }
  }

  private syncAriaExpanded (): void {
    const expanded = this.hasContentTarget && this.contentTarget.classList.contains('show')
    const trigger = this.element.querySelector('[aria-controls]')
    if (trigger != null) {
      trigger.setAttribute('aria-expanded', String(expanded))
    }
  }
}
