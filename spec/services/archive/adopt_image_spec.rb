require "rails_helper"

RSpec.describe Archive::AdoptImage do
  let(:library_path) { Dir.mktmpdir("adopt_image_spec") }
  let(:model_dir) { File.join(library_path, "model_a") }
  let(:src_dir) { File.join(library_path, "src") }
  let(:model) do
    Library.destroy_all
    library = create(:library, path: library_path)
    create(:model, library: library, path: "model_a", preview_file: nil)
  end
  let!(:archive) { create(:model_file, model: model, filename: "pack.zip", attachment: nil) }

  before { FileUtils.mkdir_p([model_dir, src_dir]) }

  after { FileUtils.rm_rf(library_path) }

  def source(name, bytes)
    path = File.join(src_dir, SecureRandom.hex(4), name)
    FileUtils.mkdir_p(File.dirname(path))
    File.binwrite(path, bytes)
    path
  end

  def entry(pathname, status: "listed")
    archive.archive_entries.create!(pathname: pathname, kind: "image", status: status)
  end

  def adopt(path, filename: File.basename(path), entry: nil)
    described_class.call(model: model, source_path: path, filename: filename, entry: entry)
  end

  it "adopts every distinct image exactly once and adds nothing on a second pass" do
    sources = %w[a b c].map { |n| source("#{n}.png", "image #{n}") }

    sources.each { |path| adopt(path) }
    expect(model.model_files.count).to eq(4) # 3 images + the archive

    expect { sources.each { |path| adopt(path) } }.not_to change { model.model_files.count }
  end

  it "links the entry to the adopted file" do
    e = entry("pics/shot.png")
    file = adopt(source("shot.png", "shot"), entry: e)

    expect(e.reload.adopted_model_file).to eq(file)
  end

  it "links an entry to an existing file with the same bytes instead of copying" do
    first = adopt(source("shot.png", "same bytes"))
    e = entry("other/shot-copy.png")

    second = adopt(source("shot-copy.png", "same bytes"), entry: e)

    expect(second).to eq(first)
    expect(e.reload.adopted_model_file).to eq(first)
    expect(File.exist?(File.join(model_dir, "shot-copy.png"))).to be false
  end

  it "keeps both images when two entries share a basename but differ in bytes" do
    a = adopt(source("1.png", "first image"))
    b = adopt(source("1.png", "second image"))

    expect([a.filename, b.filename]).to eq(["1.png", "1-1.png"])
    expect(Digest::SHA512.file(File.join(model_dir, "1.png")).hexdigest).to eq(a.digest)
    expect(Digest::SHA512.file(File.join(model_dir, "1-1.png")).hexdigest).to eq(b.digest)
  end

  it "does not adopt SVG images" do
    expect(adopt(source("logo.svg", "<svg onload=alert(1)/>"))).to be_nil
    expect(File.exist?(File.join(model_dir, "logo.svg"))).to be false
  end

  it "does not adopt a dismissed entry" do
    e = entry("pics/gone.png", status: "dismissed")

    expect(adopt(source("gone.png", "gone"), entry: e)).to be_nil
    expect(model.model_files.count).to eq(1)
  end

  it "does not reuse a same-digest record whose file is missing from disk" do
    bytes = "lost image"
    create(:model_file, model: model, filename: "lost.png", attachment: nil, digest: Digest::SHA512.hexdigest(bytes))

    file = adopt(source("found.png", bytes))

    expect(file.filename).to eq("found.png")
    expect(File.exist?(File.join(model_dir, "found.png"))).to be true
  end

  it "keeps an existing on-disk image preview" do
    File.binwrite(File.join(model_dir, "cover.png"), "cover")
    cover = create(:model_file, model: model, filename: "cover.png", attachment: nil)
    model.update!(preview_file: cover)

    adopt(source("shot.png", "shot"))

    expect(model.reload.preview_file).to eq(cover)
  end

  it "sets the adopted image as preview when the model has none" do
    file = adopt(source("shot.png", "shot"))

    expect(model.reload.preview_file).to eq(file)
  end

  it "matches, names and creates under a model lock" do
    allow(model).to receive(:with_lock).and_call_original

    adopt(source("shot.png", "shot"))

    expect(model).to have_received(:with_lock)
  end

  it "leaves no file behind when the record cannot be created" do
    allow_any_instance_of(ModelFile).to receive(:valid?).and_return(false) # rubocop:disable RSpec/AnyInstance

    expect { adopt(source("shot.png", "shot")) }.to raise_error(ActiveRecord::RecordInvalid)
    expect(File.exist?(File.join(model_dir, "shot.png"))).to be false
    expect(Dir.glob(File.join(model_dir, ".manyfold", "tmp", "*"))).to be_empty
  end

  it "cleans up the staged copy after a successful adoption" do
    adopt(source("shot.png", "shot"))

    expect(Dir.glob(File.join(model_dir, ".manyfold", "tmp", "*"))).to be_empty
  end

  it "keeps adopted filenames inside the model folder" do
    evil = adopt(source("evil.png", "evil"), filename: "../evil.png")
    nested = adopt(source("b.png", "nested"), filename: "a/../../b.png")

    expect([evil.filename, nested.filename]).to eq(["evil.png", "b.png"])
    expect(File.exist?(File.join(model_dir, "evil.png"))).to be true
    expect(File.exist?(File.join(library_path, "evil.png"))).to be false
  end

  describe "unsafe destinations" do # rubocop:disable RSpec/MultipleMemoizedHelpers
    let(:outside) { Dir.mktmpdir("adopt_image_outside") }

    after { FileUtils.rm_rf(outside) }

    it "never writes through a dangling symlink at the destination name" do
      target = File.join(outside, "victim")
      File.symlink(target, File.join(model_dir, "shot.png"))

      file = adopt(source("shot.png", "payload"))

      expect(File.exist?(target)).to be false
      expect(file.filename).to eq("shot-1.png")
      expect(File.symlink?(File.join(model_dir, "shot.png"))).to be true
    end

    it "does not delete or overwrite a pre-existing regular file when the name races" do
      File.binwrite(File.join(model_dir, "shot.png"), "mine")
      allow(model.model_files).to receive(:exists?).and_return(false)

      file = adopt(source("shot.png", "payload"))

      expect(File.binread(File.join(model_dir, "shot.png"))).to eq("mine")
      expect(file.filename).to eq("shot-1.png")
    end

    it "refuses a model folder that is a symlink out of the library" do
      FileUtils.rm_rf(model_dir)
      File.symlink(outside, model_dir)

      expect { adopt(source("shot.png", "payload")) }.to raise_error(LibraryPathJail::EscapeError)
      expect(Dir.children(outside)).to be_empty
    end

    it "uploads through the library storage for non-filesystem libraries" do
      storage = instance_double(LibraryFileSystem, upload: nil, exists?: false)
      # with_lock reloads the model, so stub every Library instance.
      allow_any_instance_of(Library).to receive_messages(storage_service: "s3", storage: storage) # rubocop:disable RSpec/AnyInstance

      adopt(source("shot.png", "payload"))

      expect(storage).to have_received(:upload).with(anything, "model_a/shot.png")
      expect(File.exist?(File.join(model_dir, "shot.png"))).to be false
    end
  end
end
