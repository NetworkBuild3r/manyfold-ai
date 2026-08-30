# frozen_string_literal: true

# INIT-013/SPEC-003 — Manyfold owns /admin/performance (HTML shell + KPI JSON).
# Full Phlex dashboard UI is SPEC-004. Gem escape hatch: /admin/rails_performance.
class PerformanceController < ApplicationController
  before_action { authorize :performance }

  after_action :verify_authorized
  skip_after_action :verify_policy_scoped, only: :index

  def index
    respond_to do |format|
      format.html # stub shell — SPEC-004
      format.json { render json: telemetry_payload }
    end
  end

  private

  def telemetry_payload
    result = Performance::Telemetry.new.call
    {
      p50: result.p50,
      p95: result.p95,
      p99: result.p99,
      throughput: result.throughput,
      sample_count: result.sample_count,
      budget_exceeded: result.budget_exceeded
    }
  end
end
