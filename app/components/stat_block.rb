# frozen_string_literal: true

class Components::StatBlock < Components::Base
  def initialize(title:, value:)
    @title = title
    @value = value
  end

  def view_template
    div(class: "inline-flex flex-col px-3 py-2 rounded-lg bg-primary-50 dark:bg-primary-900/30 text-primary-800 dark:text-primary-200 me-2") do
      div(class: "text-xs font-medium") { @title.respond_to?(:model_name) ? @title.model_name.human(count: 100) : @title.to_s }
      div(class: "text-xl mt-1") { @value.to_s }
    end
  end
end
