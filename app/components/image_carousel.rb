# frozen_string_literal: true

class Components::ImageCarousel < Components::Base
  include Phlex::Rails::Helpers::FormWith

  register_value_helper :policy

  def initialize(images:, browse: false)
    @images = images
    @browse = browse
  end

  def render?
    !@images.empty?
  end

  def view_template
    div id: carousel_dom_id,
      class: "relative w-full aspect-[4/3] rounded-xl overflow-hidden #{"mb-4" unless @browse}",
      role: "group",
      data: carousel_data,
      aria: {
        roledescription: "carousel"
      } do
      if @images.count > 1 && !@browse
        play_pause_control
      end
      div id: "#{carousel_dom_id}Inner",
        class: "absolute inset-0 overflow-hidden",
        data: {carousel_target: "inner"},
        aria: {
          atomic: false,
          live: "off"
        } do
        @images.each_with_index do |image, index|
          div class: ((index == 0) ? "carousel-item active absolute inset-0 w-full h-full" : "carousel-item absolute inset-0 w-full h-full"),
            data: {carousel_target: "slide"},
            role: "group",
            aria: {
              roledescription: "slide",
              label: translate("components.image_carousel.slide_label", index: (index + 1), count: @images.count, name: image.name)
            } do
            img src: carousel_src(image),
              alt: image.name,
              class: "block w-full h-full object-contain bg-secondary-900 dark:bg-secondary-950",
              loading: ((index <= 1) ? "eager" : "lazy"),
              decoding: "async"
            button_overlay(image) unless @browse
          end
        end
      end
      if @images.count > 1
        slide_indicators
        next_prev_controls
      end
    end
  end

  private

  def carousel_dom_id
    @browse ? "browseCarousel" : "imageCarousel"
  end

  def carousel_data
    data = {
      controller: "carousel",
      carousel_interval_value: (@browse ? 0 : 5000)
    }
    unless @browse
      data[:action] = "mouseenter->carousel#onEnter mouseleave->carousel#onLeave"
    end
    data
  end

  def play_pause_control
    button id: "rotationControl",
      class: "absolute top-2 right-2 z-20 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-white/90 dark:bg-secondary-800/90 border border-secondary-200 shadow hover:bg-white focus-visible:ring-2 focus-visible:ring-primary-500 min-w-[44px] min-h-[44px]",
      data: {action: "click->carousel#onPauseButton"} do
      Icon icon: "pause", label: t("components.image_carousel.play_pause"), id: "rotationControlIcon"
    end
  end

  def slide_indicators
    div class: "carousel-indicators absolute bottom-2 left-0 right-0 flex justify-center gap-1 z-10",
      role: "group",
      aria: {label: translate("components.image_carousel.select_slide")} do
      @images.each_with_index do |image, index|
        button type: "button",
          class: "w-2 h-2 rounded-full bg-white/50 hover:bg-white/80 dark:bg-secondary-400/80 dark:hover:bg-secondary-300 transition-colors #{"active" if index == 0}",
          data: {
            carousel_target: "indicator",
            action: "click->carousel#goTo",
            carousel_index_param: index
          },
          aria: {
            label: translate("components.image_carousel.slide_label", index: (index + 1), count: @images.count, name: image.name),
            current: (index == 0),
            disabled: (index == 0)
          }
      end
    end
  end

  def next_prev_controls
    button class: "absolute top-1/2 left-2 -translate-y-1/2 z-10 w-10 h-10 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full bg-black/30 hover:bg-black/50 dark:bg-white/20 dark:hover:bg-white/30 text-white focus-visible:ring-2 focus-visible:ring-primary-500 border-0",
      type: "button",
      tabindex: 0,
      data: {action: "click->carousel#prev"},
      aria: {label: t("components.image_carousel.previous")} do
      Icon(icon: "chevron-left", label: t("components.image_carousel.previous"))
    end
    button class: "absolute top-1/2 right-2 -translate-y-1/2 z-10 w-10 h-10 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full bg-black/30 hover:bg-black/50 dark:bg-white/20 dark:hover:bg-white/30 text-white focus-visible:ring-2 focus-visible:ring-primary-500 border-0",
      type: "button",
      tabindex: 0,
      data: {action: "click->carousel#next"},
      aria: {label: t("components.image_carousel.next")} do
      Icon(icon: "chevron-right", label: t("components.image_carousel.next"))
    end
  end

  # INIT-026/SPEC-006: mixed ModelFile + ready ArchiveEntry slides (D-3).
  def carousel_src(image)
    if archive_image?(image)
      preview_model_model_file_archive_entry_path(image.model, image.model_file, image)
    else
      model_model_file_path(image.model, image, format: image.extension, derivative: "carousel")
    end
  end

  def archive_image?(image)
    image.is_a?(ArchiveEntry)
  end

  def current_preview?(image)
    model = image.model
    if archive_image?(image)
      model.preview_archive_entry_id == image.id
    else
      model.preview_file_id == image.id
    end
  end

  def can_set_preview?(image)
    if archive_image?(image)
      policy(image.model).edit?
    else
      policy(image).edit?
    end
  end

  # ADR D-5 / REQ-007: archive rewrite-delete needs model update?, not preview show?.
  def can_delete?(image)
    if archive_image?(image)
      policy(image.model).update?
    else
      policy(image).destroy?
    end
  end

  def button_overlay(image)
    div class: "absolute bottom-0 left-0 right-0 bg-black/50 dark:bg-black/70 text-white px-3 py-2 text-sm hidden md:block" do
      span class: "inline-flex items-center rounded-full bg-secondary-800/80 px-2 py-0.5 text-xs mr-2" do
        archive_image?(image) ? t("models.gallery.source_archive") : t("models.gallery.source_loose")
      end
      if !current_preview?(image) && can_set_preview?(image)
        set_preview_form(image)
      end
      delete_control(image) if can_delete?(image)
    end
  end

  def set_preview_form(image)
    form_with model: image.model, class: "inline-block" do |form|
      if archive_image?(image)
        form.hidden_field :preview_archive_entry_id, value: image.id
      else
        form.hidden_field :preview_file_id, value: image.id
      end
      form.button t("models.file.set_as_preview"),
        class: "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-full border border-warning text-warning bg-transparent hover:bg-warning/10 mr-2"
    end
  end

  def delete_control(image)
    if archive_image?(image)
      confirm = translate("models.gallery.delete_confirm_archive", archive: image.model_file.filename, name: image.name)
      form_with url: model_model_file_archive_entry_path(image.model, image.model_file, image),
        method: :delete,
        class: "inline-block",
        data: {turbo_confirm: confirm, confirm: confirm} do |form|
        form.button class: "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-full border border-danger text-white bg-transparent hover:bg-danger/20" do
          Icon(icon: "trash", label: t("general.delete"))
        end
      end
    else
      a href: model_model_file_path(image.model, image),
        tabindex: 0,
        class: "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-full border border-danger text-white bg-transparent hover:bg-danger/20",
        data: {
          method: "delete",
          confirm: translate("models.gallery.delete_confirm_loose"),
          turbo_method: "delete",
          turbo_confirm: translate("models.gallery.delete_confirm_loose")
        } do
        Icon(icon: "trash", label: t("general.delete"))
      end
    end
  end
end
