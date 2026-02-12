# frozen_string_literal: true

class Components::DisplayUserQuota < Components::Base
  include Phlex::Rails::Helpers::NumberToHumanSize

  def initialize(current_size:, quota:)
    @quota = quota.to_f
    @current_size = current_size.to_f
  end

  def view_template
    quota_in_mb = number_to_human_size(@quota)
    current_size_in_mb = number_to_human_size(@current_size)
    percent_used = ((@current_size / @quota) * 100).ceil
    bar_class = "tw:h-4 tw:rounded tw:flex tw:items-center tw:justify-center tw:text-xs tw:font-medium tw:text-white"
    bar_class += case percent_used
    when 0..60 then " tw:bg-success"
    when 61..90 then " tw:bg-warning"
    else " tw:bg-danger"
    end
    div class: "tw:text-2xl" do
      plain "#{current_size_in_mb} / #{quota_in_mb}"
    end
    div class: "tw:w-full tw:bg-secondary-200 tw:dark:bg-secondary-700 tw:rounded tw:overflow-hidden",
      role: "progressbar",
      "aria-label": "Quota progress bar",
      "aria-valuemin": 0,
      "aria-valuemax": 100,
      "aria-valuenow": percent_used do
      div class: bar_class, style: "width:#{percent_used}%" do
        "#{percent_used}%"
      end
    end
    p class: "tw:mt-3 tw:text-left tw:text-sm tw:text-secondary-600 tw:dark:text-secondary-400" do
      t "components.display_user_quota.request_increase"
    end
  end
end
