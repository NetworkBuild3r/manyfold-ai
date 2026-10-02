# frozen_string_literal: true

# Standalone vLLM throughput probe. No Rails, no database (INIT-031/SPEC-004).
# Uses DuplicateTriage::LlmJudge.request_body so timings match the real judge.
require "json"

def duplicate_triage_load_judge!
  here = File.expand_path(__dir__)
  roots = [here, File.expand_path("../../app/services/duplicate_triage", here)]
  error_path = roots.map { |root| File.expand_path("configuration_error.rb", root) }.find { |path| File.file?(path) }
  judge_path = roots.map { |root| File.expand_path("llm_judge.rb", root) }.find { |path| File.file?(path) }
  raise "llm_judge.rb not found (looked in #{roots.join(", ")})" unless judge_path

  require error_path if error_path
  require judge_path
end

duplicate_triage_load_judge!

module DuplicateTriage
  class ThroughputProbe
    LEVELS = [1, 2, 4, 8].freeze
    DEFAULT_COUNT = 20

    def self.run(evidence_path:, count: DEFAULT_COUNT, levels: LEVELS)
      new(evidence_path: evidence_path, count: count, levels: levels).run
    end

    def self.load_evidence_file(path)
      lines = File.readlines(path, chomp: true)
      start = lines.index { |line| line.strip == "[" }
      raise "no JSON array in #{path}" unless start

      JSON.parse(lines[start..].join("\n"))
    end

    def initialize(evidence_path:, count: DEFAULT_COUNT, levels: LEVELS)
      @evidence_path = evidence_path
      @count = Integer(count)
      @levels = levels
    end

    def run
      $stdout.sync = true
      LlmJudge.configure!
      prompts = load_prompts
      rows = []
      @levels.each do |concurrency|
        row = measure(concurrency, prompts)
        rows << row
        puts format(
          "level concurrency=%d pairs/hour=%.1f p50=%.2f p95=%.2f ok=%d errors=%d",
          row[:concurrency], row[:pairs_per_hour], row[:p50], row[:p95], row[:ok], row[:errors]
        ) # rubocop:disable Rails/Output -- operator probe
      end
      print_table(rows)
      rows
    end

    private

    def load_prompts
      records = self.class.load_evidence_file(@evidence_path)
      raise "evidence file is empty" if records.empty?

      records.first(@count).map { |record| LlmJudge.request_body(record) }
    end

    def measure(concurrency, prompts)
      latencies = []
      errors = 0
      mutex = Mutex.new
      queue = Queue.new
      prompts.each_with_index { |body, index| queue << [index, body] }
      started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      workers = Array.new(concurrency) do
        Thread.new do
          loop do
            _index, body = queue.pop(true)
            t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
            begin
              LlmJudge.new.post_with_retry(body)
            rescue
              mutex.synchronize { errors += 1 }
            ensure
              mutex.synchronize { latencies << (Process.clock_gettime(Process::CLOCK_MONOTONIC) - t0) }
            end
          rescue ThreadError
            break
          end
        end
      end
      workers.each(&:join)
      wall = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
      sorted = latencies.sort
      {
        concurrency: concurrency,
        n: prompts.size,
        ok: prompts.size - errors,
        errors: errors,
        p50: percentile(sorted, 0.50),
        p95: percentile(sorted, 0.95),
        wall_s: wall,
        pairs_per_hour: (prompts.size / wall) * 3600
      }
    end

    def percentile(sorted, fraction)
      return 0.0 if sorted.empty?

      index = ((sorted.size - 1) * fraction).round
      sorted[index]
    end

    def print_table(rows)
      puts "concurrency\tpairs/hour\tp50_s\tp95_s\tok\terrors" # rubocop:disable Rails/Output -- operator probe
      rows.each do |row|
        puts [
          row[:concurrency],
          format("%.1f", row[:pairs_per_hour]),
          format("%.2f", row[:p50]),
          format("%.2f", row[:p95]),
          row[:ok],
          row[:errors]
        ].join("\t") # rubocop:disable Rails/Output -- operator probe
      end
      puts JSON.pretty_generate(rows) # rubocop:disable Rails/Output -- operator probe
    end
  end
end

if $PROGRAM_NAME == __FILE__
  path = ARGV[0] || ENV["DUPLICATE_TRIAGE_EVIDENCE_FILE"]
  raise "usage: duplicate_triage_probe.rb EVIDENCE.json (or DUPLICATE_TRIAGE_EVIDENCE_FILE)" if path.to_s.empty?

  DuplicateTriage::ThroughputProbe.run(
    evidence_path: path,
    count: Integer(ARGV[1] || ENV.fetch("DUPLICATE_TRIAGE_PROBE_N", DuplicateTriage::ThroughputProbe::DEFAULT_COUNT))
  )
end
