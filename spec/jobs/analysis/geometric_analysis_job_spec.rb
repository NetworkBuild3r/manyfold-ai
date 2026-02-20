require "rails_helper"
require "support/mock_directory"

# Minimal ASCII STL: tetrahedron (closed manifold) and T-junction (non-manifold)
MANIFOLD_STL = <<~STL
  solid test
  facet normal 0.816 -0.471 -0.333
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0.5 0.866 0
    endloop
  endfacet
  facet normal -0.816 -0.471 -0.333
    outer loop
      vertex 0 0 0
      vertex 0.5 0.866 0
      vertex 0.5 0.289 0.816
    endloop
  endfacet
  facet normal 0 -0.942 0.333
    outer loop
      vertex 0 0 0
      vertex 0.5 0.289 0.816
      vertex 1 0 0
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex 1 0 0
      vertex 0.5 0.289 0.816
      vertex 0.5 0.866 0
    endloop
  endfacet
  endsolid test
STL
NON_MANIFOLD_STL = <<~STL
  solid test
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 0 1 0
      vertex 0.5 0.5 0
    endloop
  endfacet
  endsolid test
STL

RSpec.describe Analysis::GeometricAnalysisJob do
  around do |ex|
    Dir.mktmpdir("geometric_analysis_job_spec") do |tmpdir|
      subdir = File.join(tmpdir, "geometric_analysis_job_spec")
      FileUtils.mkdir_p(subdir)
      File.write(File.join(subdir, "manifold.stl"), MANIFOLD_STL)
      File.write(File.join(subdir, "non_manifold.stl"), NON_MANIFOLD_STL)
      @library_path = tmpdir
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) }
  let(:model) { create(:model, library: library, path: "geometric_analysis_job_spec") }
  let(:manifold_mesh) {
    path = File.join(@library_path, "geometric_analysis_job_spec", "manifold.stl")
    create(:model_file, model: model, filename: "manifold.stl",
      attachment: ModelFileUploader.upload(File.open(path), :cache))
  }
  let(:non_manifold_mesh) {
    path = File.join(@library_path, "geometric_analysis_job_spec", "non_manifold.stl")
    create(:model_file, model: model, filename: "non_manifold.stl",
      attachment: ModelFileUploader.upload(File.open(path), :cache))
  }

  before do
    allow(SiteSettings).to receive(:analyse_manifold).and_return(true)
  end

  it "does not create Problems for a good mesh" do
    expect { described_class.perform_now(manifold_mesh.id) }.not_to change(Problem, :count)
  end

  it "creates a Problem for a non-manifold mesh" do # rubocop:todo RSpec/MultipleExpectations
    expect { described_class.perform_now(non_manifold_mesh.id) }.to change(Problem, :count).from(0).to(1)
    expect(Problem.first.category).to eq "non_manifold"
  end

  it "removes a manifold problem if the mesh is OK" do
    create(:problem, problematic: manifold_mesh, category: :non_manifold)
    expect { described_class.perform_now(manifold_mesh.id) }.to change(Problem, :count).from(1).to(0)
  end

  it "creates a Problem for an inside-out mesh" do # rubocop:todo RSpec/MultipleExpectations
    skip "not currently working reliably"
    expect { described_class.perform_now(flipped_mesh.id) }.to change(Problem, :count).from(0).to(1)
    expect(Problem.first.category).to eq "inside_out"
  end

  it "removes an inside-out problem if the mesh is OK" do
    skip "not currently working reliably"
    create(:problem, problematic: manifold_mesh, category: :inside_out)
    expect { described_class.perform_now(manifold_mesh.id) }.to change(Problem, :count).from(1).to(0)
  end

  it "raises exception if file ID is not found" do
    expect { described_class.perform_now(nil) }.to raise_error(ActiveRecord::RecordNotFound)
  end
end
