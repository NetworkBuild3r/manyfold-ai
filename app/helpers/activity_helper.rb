module ActivityHelper
  def status_icon(status)
    case status
    when :queued
      Icon(icon: "hourglass", label: translate("activity_helper.status_icon.queued"))
    when :working
      Icon(icon: "gear", label: translate("activity_helper.status_icon.working"), effect: "icon-spin")
    when :completed
      Icon(icon: "check2-circle", label: translate("activity_helper.status_icon.completed"))
    when :failed
      Icon(icon: "exclamation-diamond", label: translate("activity_helper.status_icon.error"))
    end
  end

  def activity_row_style(status)
    case status
    when :working
      "tw:bg-info/10"
    when :completed
      "tw:bg-success/10"
    when :failed
      "tw:bg-danger/10"
    end
  end
end
