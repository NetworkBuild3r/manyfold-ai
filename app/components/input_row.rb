# frozen_string_literal: true

class Components::InputRow < Components::Base
  def initialize(form:, attribute:, label:, help: nil, options: {})
    @form = form
    @attribute = attribute
    @attribute_without_id = @attribute.to_s.gsub("_id", "")
    @label = label
    @help = help
    @options = options
  end

  def view_template
    div do
      @form.label(@attribute, @label, class: label_class)
    end
    div(class: "mt-1") do
      input_group
      errors_for(@form.object, @attribute_without_id)
      help
    end
  end

  def label_class
    "block text-sm font-medium text-secondary-700 dark:text-secondary-200"
  end

  def input_group
    div(class: "flex") do
      input_element
    end
  end

  def input_element
    raise NotImplementedError
  end

  def help
    span(class: "text-sm text-secondary-500 dark:text-secondary-300 mt-1 block") { @help } if @help
  end

  def errors_for(object, attribute)
    return if object.nil? || attribute.nil?
    return unless object.errors.include? attribute
    div(class: "text-danger text-sm mt-1") do
      object.errors.full_messages_for(attribute).join("; ")
    end
  end
end
