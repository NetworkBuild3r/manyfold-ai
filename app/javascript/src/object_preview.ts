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
}

export class ObjectPreview {
  progressBar: HTMLDivElement | null
  progressLabel: HTMLSpanElement | null
  canvas: HTMLCanvasElement
  renderer: OffscreenRendererProxy | null = null
  observer: IntersectionObserver | null = null
  loading: boolean = false
  worker: Worker | null = null

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
    this.boundLoad = this.load.bind(this)
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
    window.addEventListener('resize', this.boundResize)
    this.onResize()
    const pointerEvents: Array<keyof HTMLElementEventMap> = ['pointerdown', 'pointermove', 'pointerup']
    pointerEvents.forEach((name) => this.canvas.addEventListener(name, this.boundPointer as EventListener))
    const keyEvents: Array<keyof HTMLElementEventMap> = ['keydown', 'keyup']
    keyEvents.forEach((name) => this.canvas.addEventListener(name, this.boundKey as EventListener))
    const otherEvents: Array<keyof HTMLElementEventMap> = ['wheel', 'contextmenu']
    otherEvents.forEach((name) => this.canvas.addEventListener(name, this.boundEvent))
    this.observer = new window.IntersectionObserver(this.boundIntersection, {})
    this.observer.observe(this.canvas)
    const loadButton = this.canvas.parentElement?.getElementsByClassName('object-preview-progress')[0] as HTMLDivElement | undefined
    if (loadButton != null) loadButton.addEventListener('click', this.boundLoad)
  }

  disconnect (): void {
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
    this.worker?.terminate()
    this.worker = null
  }

  onIntersectionChanged (entries: IntersectionObserverEntry[]): void {
    if ((this.canvas.dataset.autoLoad === 'true') && (entries[0]?.isIntersecting)) {
      void this.load()
    }
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
