# frozen_string_literal: true

class Components::DropdownHeader < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  def initialize(text:)
    @text = text
  end

  def view_template
    li role: "presentation" do
      h6(class: "tw:px-3 tw:py-1.5 tw:text-xs tw:font-semibold tw:uppercase tw:text-secondary-500 tw:dark:text-secondary-400 tw:my-0") { @text }
    end
  end
end
