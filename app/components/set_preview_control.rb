# frozen_string_literal: true

# INIT-027/SPEC-010 — one set-as-preview PATCH for loose file or archive entry.
class Components::SetPreviewControl < Components::Base
  include Phlex::Rails::Helpers::ButtonTo

  def initialize(model:, preview_file_id: nil, preview_archive_entry_id: nil, label: nil, variant: "outline-warning")
    @model = model
    @preview_file_id = preview_file_id
    @preview_archive_entry_id = preview_archive_entry_id
    @label = label
    @variant = variant.to_s
  end

  def view_template
    button_to model_path(@model),
      method: :patch,
      params: preview_params,
      class: button_class do
      @label || t("models.file.set_as_preview")
    end
  end

  private

  def preview_params
    if @preview_archive_entry_id
      {model: {preview_archive_entry_id: @preview_archive_entry_id}}
    else
      {model: {preview_file_id: @preview_file_id}}
    end
  end

  def button_class
    variant = Components::BaseButton::VARIANT_CLASSES[@variant] || Components::BaseButton::VARIANT_CLASSES["outline-warning"]
    return variant if variant.start_with?(Components::BaseButton::BASE_CLASSES)

    [Components::BaseButton::BASE_CLASSES, variant].join(" ")
  end
end
