# frozen_string_literal: true

require "rails_helper"

RSpec.describe "scripts/mesh_thumbnail.mjs" do
  it "renders a valid PNG from a tiny ASCII STL" do
    skip "node not on PATH" unless system("command", "-v", "node", out: File::NULL, err: File::NULL)

    script = Rails.root.join("scripts/mesh_thumbnail.mjs")
    expect(script).to be_file

    Dir.mktmpdir("mesh_thumb_spec") do |dir|
      stl = File.join(dir, "tri.stl")
      png = File.join(dir, "out.png")
      File.write(stl, <<~STL)
        solid t
          facet normal 0 0 1
            outer loop
              vertex 0 0 0
              vertex 1 0 0
              vertex 0 1 0
            endloop
          endfacet
        endsolid t
      STL

      ok = system("node", script.to_s, stl, png, "128", "96", out: File::NULL, err: File::NULL)
      expect(ok).to be true
      expect(File.binread(png, 8)).to eq("\x89PNG\r\n\x1a\n".b)
      expect(File.size(png)).to be > 100
    end
  end
end
