import * as Comlink from 'comlink'
import './comlink_event_handler'
import type { OffscreenRenderer } from '../offscreen_renderer'

export interface OffscreenRendererProxy {
  handleEvent: (event: Event) => void
  onResize: (width: number, height: number, pixelRatio: number) => void
  load: (
    cbComplete: () => void,
    cbProgress: (percentage: number) => void,
    cbError: () => void
  ) => Promise<void>
  cleanup: () => void
}

export class ObjectPreview {
  progressBar: HTMLDivElement | null
  progressLabel: HTMLSpanElement | null
  canvas: HTMLCanvasElement
  renderer: OffscreenRendererProxy | null = null
  observer: IntersectionObserver | null = null
  loading: boolean = false
  worker: Worker | null = null
  private connected: boolean = false

  private readonly boundResize: () => void
  private readonly boundPointer: (e: PointerEvent) => void
  private readonly boundKey: (e: KeyboardEvent) => void
  private readonly boundEvent: (e: Event) => void
  private readonly boundIntersection: (entries: IntersectionObserverEntry[]) => void
  private readonly boundLoad: () => void

  constructor (canvas: HTMLCanvasElement) {
    this.canvas = canvas
    this.progressBar = this.canvas.parentElement?.getElementsByClassName('progress-bar')[0] as HTMLDivElement ?? null
    this.progressLabel = this.canvas.parentElement?.getElementsByClassName('progress-label')[0] as HTMLSpanElement ?? null
    this.boundResize = this.onResize.bind(this)
    this.boundPointer = this.onPointerEvent.bind(this)
    this.boundKey = this.onKeyEvent.bind(this)
    this.boundEvent = this.onEvent.bind(this)
    this.boundIntersection = this.onIntersectionChanged.bind(this)
    this.boundLoad = () => { void this.load() }
  }

  async initializeOffscreenRenderer (): Promise<void> {
    if (this.canvas.dataset.workerUrl === undefined || this.canvas.dataset.workerUrl === null) {
      console.error('[ObjectPreview] Could not load worker: workerUrl missing')
      return
    }
    try {
      const offscreenCanvas = this.canvas.transferControlToOffscreen()
      this.worker = new Worker(this.canvas.dataset.workerUrl, { type: 'module' })
      const RemoteOffscreenRenderer = await Comlink.wrap<typeof OffscreenRenderer>(this.worker)
      this.renderer = await new RemoteOffscreenRenderer(
        Comlink.transfer(offscreenCanvas as unknown as HTMLCanvasElement, [offscreenCanvas]), { ...this.canvas.dataset }
      ) as unknown as OffscreenRendererProxy
      this.onResize()
    } catch (error) {
      console.error('[ObjectPreview] Failed to initialize offscreen renderer:', error)
    }
  }

  connect (): void {
    this.connected = true
    window.addEventListener('resize', this.boundResize)
    this.onResize()
    const pointerEvents: Array<keyof HTMLElementEventMap> = ['pointerdown', 'pointermove', 'pointerup']
    pointerEvents.forEach((name) => this.canvas.addEventListener(name, this.boundPointer as EventListener))
    const keyEvents: Array<keyof HTMLElementEventMap> = ['keydown', 'keyup']
    keyEvents.forEach((name) => this.canvas.addEventListener(name, this.boundKey as EventListener))
    const otherEvents: Array<keyof HTMLElementEventMap> = ['wheel', 'contextmenu']
    otherEvents.forEach((name) => this.canvas.addEventListener(name, this.boundEvent))
    this.observer = new window.IntersectionObserver(this.boundIntersection, {
      // Unload a little before fully leaving so memory frees while scrolling lists
      rootMargin: '50px'
    })
    this.observer.observe(this.canvas)
    const loadButton = this.canvas.parentElement?.getElementsByClassName('object-preview-progress')[0] as HTMLDivElement | undefined
    if (loadButton != null) loadButton.addEventListener('click', this.boundLoad)
  }

  disconnect (): void {
    this.connected = false
    window.removeEventListener('resize', this.boundResize)
    const pointerEvents: Array<keyof HTMLElementEventMap> = ['pointerdown', 'pointermove', 'pointerup']
    pointerEvents.forEach((name) => this.canvas.removeEventListener(name, this.boundPointer as EventListener))
    const keyEvents: Array<keyof HTMLElementEventMap> = ['keydown', 'keyup']
    keyEvents.forEach((name) => this.canvas.removeEventListener(name, this.boundKey as EventListener))
    const otherEvents: Array<keyof HTMLElementEventMap> = ['wheel', 'contextmenu']
    otherEvents.forEach((name) => this.canvas.removeEventListener(name, this.boundEvent))
    this.observer?.disconnect()
    this.observer = null
    const loadButton = this.canvas.parentElement?.getElementsByClassName('object-preview-progress')[0] as HTMLDivElement | undefined
    if (loadButton != null) loadButton.removeEventListener('click', this.boundLoad)
    this.releaseResources()
  }

  /**
   * Free the WebGL worker and renderer. After transferControlToOffscreen the
   * canvas is dead; callers that need to reload must replace the canvas element.
   */
  releaseResources (): void {
    try {
      this.renderer?.cleanup()
    } catch {
      // Worker may already be dead
    }
    this.worker?.terminate()
    this.worker = null
    this.renderer = null
    this.loading = false
  }

  onIntersectionChanged (entries: IntersectionObserverEntry[]): void {
    const entry = entries[0]
    if (entry == null) return

    if (entry.isIntersecting) {
      if (this.canvas.dataset.autoLoad === 'true') {
        void this.load()
      }
      return
    }

    // Scrolled off-screen: free worker + GPU memory. Replace canvas so a later
    // load (or re-entry with auto-load) can transferControlToOffscreen again.
    if (this.worker != null || this.renderer != null) {
      this.releaseResources()
      this.replaceDeadCanvas()
    }
  }

  /**
   * After transferControlToOffscreen(), the original canvas cannot be reused.
   * Swap in a fresh canvas with the same attributes; Stimulus will reconnect.
   */
  private replaceDeadCanvas (): void {
    if (!this.connected) return
    const old = this.canvas
    const parent = old.parentElement
    if (parent == null) return

    const fresh = document.createElement('canvas')
    for (const attr of Array.from(old.attributes)) {
      fresh.setAttribute(attr.name, attr.value)
    }
    // Ensure progress UI exists again if it was removed after a successful load
    this.ensureProgressUi(parent)

    old.replaceWith(fresh)
    // Stimulus disconnects this controller and connects a new one on `fresh`.
  }

  private ensureProgressUi (container: HTMLElement): void {
    if (container.getElementsByClassName('object-preview-progress').length > 0) return

    const progress = document.createElement('div')
    progress.className = 'object-preview-progress absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 px-4 py-2 rounded-lg bg-secondary-200 dark:bg-secondary-700 border border-secondary-300 dark:border-secondary-600'
    progress.setAttribute('role', 'presentation')
    progress.innerHTML = `
      <div class="progress-bar h-2 bg-primary-500 rounded overflow-hidden mb-2" role="progressbar" style="width: 0%" aria-label="Loading progress" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
      <span class="progress-label text-sm font-medium block" role="button">Load</span>
    `
    container.appendChild(progress)
  }

  onPointerEvent (event: PointerEvent): void {
    if (event.type === 'pointerdown') {
      this.canvas.focus()
      this.canvas.setPointerCapture(event.pointerId)
    }
    this.onEvent(event)
  }

  onKeyEvent (event: KeyboardEvent): void {
    if ([
      'ArrowUp',
      'ArrowDown',
      'ArrowLeft',
      'ArrowRight',
      'Minus',
      'Equal'
    ].includes(event.code)) {
      this.onEvent(event)
    }
  }

  onEvent (event: Event): void {
    event.preventDefault()
    this.renderer?.handleEvent(event)
  }

  onLoadProgress (percentage: number): void {
    if ((this.progressBar == null) || (this.progressLabel == null)) { return }
    if (percentage === 100) {
      this.progressLabel.textContent = window.i18n.t('renderer.processing')
    } else {
      this.progressLabel.textContent = `${percentage}%`
    }
    this.progressBar.style.width = `${percentage}%`
    this.progressBar.ariaValueNow = percentage.toString()
  }

  onLoad (): void {
    this.progressBar?.parentElement?.remove()
    this.progressBar = null
    this.progressLabel = null
  }

  onLoadError (): void {
    if ((this.progressBar == null) || (this.progressLabel == null)) { return }
    this.progressBar.classList.add('bg-danger')
    this.progressBar.style.width = this.progressBar.ariaValueNow = '100%'
    this.progressLabel.textContent = window.i18n.t('renderer.errors.load')
  }

  onResize (): void {
    this.renderer?.onResize(
      this.canvas.clientWidth,
      this.canvas.clientHeight,
      window.devicePixelRatio
    )
  }

  async load (): Promise<void> {
    if (this.loading) { return }
    this.loading = true
    await this.initializeOffscreenRenderer()
    await this.renderer?.load(
      Comlink.proxy(this.onLoad.bind(this)),
      Comlink.proxy(this.onLoadProgress.bind(this)),
      Comlink.proxy(this.onLoadError.bind(this))
    )
  }
}
