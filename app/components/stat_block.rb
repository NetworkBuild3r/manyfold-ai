# frozen_string_literal: true

class Components::StatBlock < Components::Base
  def initialize(title:, value:)
    @title = title
    @value = value
  end

  def view_template
    div(class: "tw:inline-flex tw:flex-col tw:px-3 tw:py-2 tw:rounded-lg tw:bg-primary-50 tw:dark:bg-primary-900/30 tw:text-primary-800 tw:dark:text-primary-200 tw:me-2") do
      div(class: "tw:text-xs tw:font-medium") { @title.respond_to?(:model_name) ? @title.model_name.human(count: 100) : @title.to_s }
      div(class: "tw:text-xl tw:mt-1") { @value.to_s }
    end
  end
end
