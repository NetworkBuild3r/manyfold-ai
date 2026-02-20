# frozen_string_literal: true

class Components::PasswordInputRow < Components::InputRow
  def initialize(form:, attribute:, label:, help: nil, options: {})
    @field_options = {class: Components::TextInputRow::INPUT_CLASS}.merge(options)
    super
  end

  def input_group
    div(class: "flex") do
      raw @form.password_field(@attribute, @field_options) # rubocop:disable Rails/OutputSafety
    end
  end
end
