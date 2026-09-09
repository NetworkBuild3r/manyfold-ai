import { Controller } from '@hotwired/stimulus'

// Opens the merge comparison <dialog> when the Turbo Frame loads it.
export default class extends Controller {
  static targets = ['dialog']

  declare readonly dialogTarget: HTMLDialogElement

  private readonly boundClosed = (): void => { this.element.remove() }

  connect (): void {
    this.dialogTarget.addEventListener('close', this.boundClosed)
    this.dialogTarget.showModal()
  }

  disconnect (): void {
    this.dialogTarget.removeEventListener('close', this.boundClosed)
    if (this.dialogTarget.open) this.dialogTarget.close()
  }

  close (event?: Event): void {
    event?.preventDefault()
    this.dialogTarget.close()
  }

  pickOverride (event: Event): void {
    const input = event.currentTarget as HTMLInputElement
    const field = input.dataset.mergeField
    if (field == null) return
    const radio = this.element.querySelector<HTMLInputElement>(
      `input[type="radio"][name="fields[${field}]"][value="override"]`
    )
    if (radio != null) radio.checked = true
  }
}
