import { Controller } from '@hotwired/stimulus'

// Shows the storage options section that matches the select value; hides the rest.
// Uses .show class for visibility (Bootstrap .collapse styling). No Bootstrap JS dependency.
export default class extends Controller {
  connect (): void {
    this.onChange()
  }

  onChange (): void {
    this.updateSections((this.element as HTMLSelectElement).value)
  }

  updateSections (active: string): void {
    const selected = 'options-' + active
    document.querySelectorAll('.storage-collapse').forEach((section: Element) => {
      const el = section as HTMLElement
      if (el.id === selected) {
        el.classList.add('show')
      } else {
        el.classList.remove('show')
      }
    })
  }
}
