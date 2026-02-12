# frozen_string_literal: true

class Components::DropdownDivider < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  def initialize
  end

  def view_template
    li(role: "presentation") { hr(class: "tw:my-1 tw:border-t tw:border-secondary-200 tw:dark:border-secondary-600 tw:border-0") }
  end
end
