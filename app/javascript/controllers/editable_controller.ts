import { Controller } from '@hotwired/stimulus'

// Connects to data-controller="editable"
export default class extends Controller {
  input (): HTMLInputElement {
    return this.element as HTMLInputElement
  }

  field (): string {
    return this.input().dataset.editableField ?? ''
  }

  path (): string {
    return this.input().dataset.editablePath ?? ''
  }

  value (): string {
    return this.input().innerText?.trim()
  }

  initialText: string | null = null

  onKeypress (event: KeyboardEvent): void {
    if (event.which === 13) { event.preventDefault() }
  }

  onFocus (): void {
    this.initialText = this.value()
  }

  onBlur (): void {
    if (this.initialText !== this.value()) {
      const data = new FormData()
      data.append(this.field(), this.value())
      data.append('authenticity_token', document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ?? '')
      void this.saveValue(data)
    }
  }

  private async saveValue (data: FormData): Promise<void> {
    try {
      const response = await fetch(this.path(), {
        method: 'PATCH',
        redirect: 'manual',
        body: data
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
    } catch (error) {
      console.error('[editable] Save failed:', error)
    }
  }
}
