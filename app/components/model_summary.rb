# frozen_string_literal: true

class Components::ModelSummary < Components::ModelCard
  def initialize(model:)
    @model = model
  end

  def view_template
    div(class: "tw:rounded-xl tw:border tw:border-secondary-200 tw:dark:border-secondary-600 tw:bg-white tw:dark:bg-secondary-800 tw:shadow-sm tw:mb-4") do
      div(class: "tw:p-4 tw:flex tw:flex-wrap tw:items-start tw:gap-x-4 tw:gap-y-2") do
        div(class: "tw:min-w-0 tw:flex-1") do
          h5(class: "tw:text-lg tw:font-medium tw:text-secondary-900 tw:dark:text-secondary-100 tw:mt-0 tw:mb-1") { @model.name }
          span { @model.model_files.count }
          whitespace
          span { ModelFile.model_name.human count: @model.model_files.count }
          span { " : " }
          code(class: "tw:text-sm tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { @model.path }
        end
        div(class: "tw:flex-shrink-0") do
          credits
          div(class: "tw:flex tw:flex-wrap tw:gap-1 tw:mt-1") { @model.tags.map { |it| Tag(tag: it) } }
        end
      end
    end
  end
end
