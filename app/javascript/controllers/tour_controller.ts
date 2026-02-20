import { Controller } from '@hotwired/stimulus'
import { driver, Driver, DriveStep, Config, State } from 'driver.js'

// Connects to data-controller="tour"
export default class extends Controller {
  driverObject: Driver | null = null
  completed: string[] = []

  connect (): void {
    // Tour is opt-in; no auto-start
  }

  start (): void {
    const tourElements = document.querySelectorAll('[data-tour-id-completed="false"]')
    if (tourElements.length === 0) return

    const tourSteps = [...tourElements].map((stepElement: HTMLElement) => (
      {
        element: '#' + stepElement.id,
        popover: {
          title: stepElement.dataset.tourTitle,
          description: stepElement.dataset.tourDescription
        }
      }
    ))
    this.driverObject = driver({
      onHighlighted: this.onHighlighted.bind(this),
      onDestroyStarted: this.onDestroyStarted.bind(this),
      showProgress: true,
      steps: tourSteps
    })
    this.driverObject.drive()
  }

  onHighlighted (element: Element, step: DriveStep, options: { config: Config, state: State, driver: Driver }): void {
    this.completed.push(element.id)
  }

  onDestroyStarted (): void {
    // Store tour state back into current user
    const xhr = new XMLHttpRequest()
    xhr.open('PATCH', '/users.json', true)
    xhr.setRequestHeader('Content-Type', 'application/json')
    xhr.onerror = () => {
      console.error('[tour] Failed to persist tour state')
    }
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        console.error('[tour] Persist tour state failed:', xhr.status)
      }
    }
    xhr.send(JSON.stringify({
      user: {
        tour_state: {
          completed: {
            add: this.completed
          }
        }
      }
    }))
    // Done, close the tour
    this.driverObject?.destroy()
  }

  disconnect (): void {
    if (this.driverObject != null) {
      this.driverObject.destroy()
      this.driverObject = null
    }
  }
}
