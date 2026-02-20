# frozen_string_literal: true

class Components::RichTextInputRow < Components::InputRow
  def input_element
    @form.text_area(@attribute, {class: Components::TextInputRow::INPUT_CLASS}.merge(@options))
  end
end
