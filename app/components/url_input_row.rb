# frozen_string_literal: true

class Components::UrlInputRow < Components::InputRow
  def input_element
    raw @form.url_field(@attribute, {class: Components::TextInputRow::INPUT_CLASS}.merge(@options)) # rubocop:disable Rails/OutputSafety
  end
end
