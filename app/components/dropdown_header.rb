# frozen_string_literal: true

class Components::DropdownHeader < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  def initialize(text:)
    @text = text
  end

  def view_template
    li role: "presentation" do
      h6(class: "px-3 py-1.5 text-xs font-semibold uppercase text-secondary-500 dark:text-secondary-400 my-0") { @text }
    end
  end
end
