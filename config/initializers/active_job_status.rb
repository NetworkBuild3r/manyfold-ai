# Sidekiq and Rails communicate via redis, so we should always use that.
ActiveJob::Status.store = :redis_cache_store, {
  url: ENV.fetch("REDIS_URL", "redis://localhost:6379"),
  pool: {
    size: ActiveRecord::Base.connection_pool.size
  }
}

ActiveJob::Status.options = {
  includes: %i[status serialized_job exception],
  expires_in: 24.hours.to_i
}

module ActiveJob::Status
  # Completed archive-rescan rows can number in the hundreds of thousands.
  # The activity page only needs in-flight / failed work plus a recent sample.
  LIST_COMPLETED_CAP = 200

  def self.all
    inflight = []
    completed = []
    each_status do |status|
      case status[:status]&.to_sym
      when :queued, :working, :failed, :retrying
        inflight << status
      when :completed
        completed << status if completed.size < LIST_COMPLETED_CAP
      else
        inflight << status
      end
    end
    inflight + completed
  end

  def self.each_status
    store.redis.with do |conn|
      cursor = "0"
      loop do
        cursor, keys = conn.scan(cursor, match: "activejob:status:*", count: 250)
        keys.each { |key| yield get(key.split(":").last) }
        break if cursor == "0"
      end
    end
  end
end

class ActiveJob::Status::Status
  def last_activity
    [
      coerce_activity_time(read.dig(:serialized_job, "enqueued_at")),
      coerce_activity_time(read[:started_at]),
      coerce_activity_time(read[:finished_at])
    ].compact.max
  end

  private

  def coerce_activity_time(value)
    case value
    when nil
      nil
    when Time, ActiveSupport::TimeWithZone
      value.to_time
    when DateTime
      value.to_time
    when String
      return if value.blank?

      Time.iso8601(value)
    end
  rescue ArgumentError, TypeError
    Time.zone.parse(value.to_s)
  rescue ArgumentError, TypeError
    nil
  end
end
