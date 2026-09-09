# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::ProblemRow, type: :component do
  let(:model) { create(:model, name: "Bleach Ichigo Diorama Hq") }
  let(:file) do
    create(:model_file, model: model, filename: "ichigo_diorama_v2_hollow.stl").tap do |model_file|
      # Factory attachment is an empty IO; persist the library size the row reads.
      model_file.update_column(:size, 142.megabytes) # rubocop:disable Rails/SkipsModelValidations
    end
  end
  let(:problem) { create(:problem, category: :duplicate, problematic: file, note: "Photo 2020 04 01 17 05 41") }

  it "renders a full-width card row with title, file meta, and view control" do # rubocop:todo RSpec/MultipleExpectations
    html = render described_class.new(problem: problem, user: nil)
    expect(html).to include("problem-row")
    expect(html).to include("Bleach Ichigo Diorama Hq")
    expect(html).to include("ichigo_diorama_v2_hollow.stl")
    expect(html).to include("142 MB")
    expect(html).to include("Photo 2020 04 01 17 05 41")
    expect(html).to include(%(id="problem-#{problem.id}"))
    expect(html).not_to include('data-collapse-target="content"')
  end

  it "does not emit table cells" do
    html = render described_class.new(problem: problem, user: nil)
    expect(html).not_to include("<td")
    expect(html).not_to include("<tr")
  end

  it "places the two matching models side by side" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    other = create(:model, name: "Ichigo Copy Final")
    twin = create(:model_file, model: other, filename: "hero_copy.stl")
    file.update_column(:digest, "dup") # rubocop:disable Rails/SkipsModelValidations
    twin.update_column(:digest, "dup") # rubocop:disable Rails/SkipsModelValidations
    pair = Problem::DuplicatePair.build(problem)

    html = render described_class.new(problem: problem, user: nil, pair: pair)
    expect(html).to include("Bleach Ichigo Diorama Hq")
    expect(html).to include("Ichigo Copy Final")
    expect(html).to include("ichigo_diorama_v2_hollow.stl")
    expect(html).to include("hero_copy.stl")
    expect(html).to include(I18n.t("problems.index.versus"))
  end
end
