# frozen_string_literal: true

class Components::ModelSummary < Components::ModelCard
  def initialize(model:)
    @model = model
  end

  def view_template
    div(class: "rounded-xl border border-secondary-200 dark:border-secondary-600 bg-surface dark:bg-surface-dark shadow-sm mb-4") do
      div(class: "p-4 flex flex-wrap items-start gap-x-4 gap-y-2") do
        div(class: "min-w-0 flex-1") do
          h5(class: "text-lg font-medium text-secondary-900 dark:text-secondary-100 mt-0 mb-1") { @model.name }
          span { @model.model_files.count }
          whitespace
          span { ModelFile.model_name.human count: @model.model_files.count }
          span { " : " }
          code(class: "text-sm bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { @model.path }
        end
        div(class: "flex-shrink-0") do
          credits
          div(class: "flex flex-wrap gap-1 mt-1") { @model.tags.map { |it| Tag(tag: it) } }
        end
      end
    end
  end
end
