import { Controller } from '@hotwired/stimulus'
import { ObjectPreview } from '../src/object_preview'

// Connects to data-controller="renderer"
export default class extends Controller {
  preview: ObjectPreview

  connect (): void {
    this.preview = new ObjectPreview(this.element as HTMLCanvasElement)
    this.preview.connect()
  }

  disconnect (): void {
    this.preview.disconnect()
  }
}
