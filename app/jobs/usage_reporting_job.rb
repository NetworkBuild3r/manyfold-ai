require "net/http"

class UsageReportingJob < ApplicationJob
  def perform
    return unless SiteSettings.anonymous_usage_id
    return unless UsageReport.configured?

    uri = URI.parse(UsageReport.endpoint)
    data = UsageReport.generate
    Rails.logger.info("Sending anonymous usage report to #{uri}: #{data}")
    headers = {
      "Content-Type": "application/json",
      "User-Agent": "LibraryUsageReportingJob"
    }
    Net::HTTP.post(uri, data, headers)
  end
end
