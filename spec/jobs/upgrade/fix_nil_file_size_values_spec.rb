# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Upgrade::FixNilFileSizeValues do
  around do |example|
    Dir.mktmpdir("fix_nil_file_size_values") do |tmpdir|
      model_subdir = File.join(tmpdir, "fix_nil_file_size_values_spec")
      FileUtils.mkdir_p(model_subdir)
      example_obj_src = Rails.root.join("spec/fixtures/model_file_spec/example.obj")
      FileUtils.cp(example_obj_src, model_subdir) if File.exist?(example_obj_src)
      @library_path = tmpdir
      example.run
    end
  end

  let(:library) { create(:library, path: @library_path) }
  let(:model1) { create(:model, library: library, path: "fix_nil_file_size_values_spec") }
  let(:part) { create(:model_file, model: model1, filename: "example.obj", size: 284) }

  it "updates file with nil size" do
    part.update(size: nil)
    described_class.perform_now
    part.reload
    expect(part.size).not_to be_nil
  end
end
