# frozen_string_literal: true

class Components::DropdownDivider < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  def initialize
  end

  def view_template
    li(role: "presentation") { hr(class: "my-1 border-t border-secondary-200 dark:border-secondary-600 border-0") }
  end
end
