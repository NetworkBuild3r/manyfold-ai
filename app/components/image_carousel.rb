# frozen_string_literal: true

class Components::ImageCarousel < Components::Base
  include Phlex::Rails::Helpers::FormWith

  register_value_helper :policy

  def initialize(images:)
    @images = images
  end

  def render?
    !@images.empty?
  end

  def view_template
    div id: "imageCarousel",
      class: "tw:relative tw:rounded-xl tw:overflow-hidden tw:mb-4",
      role: "group",
      data: {
        controller: "carousel",
        action: "mouseenter->carousel#onEnter mouseleave->carousel#onLeave"
      },
      aria: {
        roledescription: "carousel"
      } do
      if @images.count > 1
        play_pause_control
      end
      div id: "imageCarouselInner",
        class: "tw:relative tw:overflow-hidden",
        data: {carousel_target: "inner"},
        aria: {
          atomic: false,
          live: "off"
        } do
        @images.each_with_index do |image, index|
          div class: (index == 0 ? "carousel-item active" : "carousel-item"),
            data: {carousel_target: "slide"},
            role: "group",
            aria: {
              roledescription: "slide",
              label: translate("components.image_carousel.slide_label", index: (index + 1), count: @images.count, name: image.name)
            } do
            img src: model_model_file_path(image.model, image, format: image.extension, derivative: "carousel"),
              alt: image.name,
              class: "tw:block tw:w-full tw:h-auto",
              loading: (index <= 1 ? "eager" : "lazy"),
              decoding: "async"
            button_overlay(image)
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

  def play_pause_control
    button id: "rotationControl",
      class: "tw:absolute tw:top-2 tw:right-2 tw:z-20 tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:bg-white/90 tw:dark:bg-secondary-800/90 tw:border tw:border-secondary-200 tw:shadow tw:hover:bg-white tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:min-w-[44px] tw:min-h-[44px]",
      data: {action: "click->carousel#onPauseButton"} do
      Icon icon: "pause", label: t("components.image_carousel.play_pause"), id: "rotationControlIcon"
    end
  end

  def slide_indicators
    div class: "carousel-indicators tw:absolute tw:bottom-2 tw:left-0 tw:right-0 tw:flex tw:justify-center tw:gap-1 tw:z-10",
      role: "group",
      aria: {label: translate("components.image_carousel.select_slide")} do
      @images.each_with_index do |image, index|
        button type: "button",
          class: "tw:w-2 tw:h-2 tw:rounded-full tw:bg-white/50 tw:hover:bg-white/80 tw:transition-colors #{'active' if index == 0}",
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
    button class: "tw:absolute tw:top-1/2 tw:left-2 tw:-translate-y-1/2 tw:z-10 tw:w-10 tw:h-10 tw:min-w-[44px] tw:min-h-[44px] tw:flex tw:items-center tw:justify-center tw:rounded-full tw:bg-black/30 tw:hover:bg-black/50 tw:text-white tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:border-0",
      type: "button",
      tabindex: 0,
      data: {action: "click->carousel#prev"},
      aria: {label: t("components.image_carousel.previous")} do
      Icon(icon: "chevron-left", label: t("components.image_carousel.previous"))
    end
    button class: "tw:absolute tw:top-1/2 tw:right-2 tw:-translate-y-1/2 tw:z-10 tw:w-10 tw:h-10 tw:min-w-[44px] tw:min-h-[44px] tw:flex tw:items-center tw:justify-center tw:rounded-full tw:bg-black/30 tw:hover:bg-black/50 tw:text-white tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:border-0",
      type: "button",
      tabindex: 0,
      data: {action: "click->carousel#next"},
      aria: {label: t("components.image_carousel.next")} do
      Icon(icon: "chevron-right", label: t("components.image_carousel.next"))
    end
  end

  def button_overlay(image)
    div class: "tw:absolute tw:bottom-0 tw:left-0 tw:right-0 tw:bg-black/50 tw:text-white tw:px-3 tw:py-2 tw:text-sm tw:hidden tw:md:block" do
      if image.model.preview_file != image && policy(image).edit?
        form_with model: image.model, class: "tw:inline-block" do |form|
          form.hidden_field :preview_file_id, value: image.id
          form.button t("models.file.set_as_preview"),
            class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-2 tw:py-1 tw:text-xs tw:font-medium tw:rounded tw:border tw:border-warning tw:text-warning tw:bg-transparent tw:hover:bg-warning/10 tw:mr-2"
        end
      end
      if policy(image).destroy?
        a href: model_model_file_path(image.model, image),
          tabindex: 0,
          class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-2 tw:py-1 tw:text-xs tw:font-medium tw:rounded tw:border tw:border-danger tw:text-white tw:bg-transparent tw:hover:bg-danger/20",
          data: {
            method: "delete",
            confirm: translate("model_files.destroy.confirm")
          } do
          Icon(icon: "trash", label: t("general.delete"))
        end
      end
    end
  end
end
