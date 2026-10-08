require "rails_helper"
require "zip"

RSpec.describe Archive::RemoveEntries do
  let(:library_path) { Dir.mktmpdir("remove_entries_spec") }
  let(:model_dir) { File.join(library_path, "model_a") }
  let(:model) do
    Library.destroy_all
    create(:model, library: create(:library, path: library_path), path: "model_a")
  end
  let(:files) { {"readme.txt" => "hello", "pics/shot.png" => "png bytes", "pics/other.png" => "other"} }

  before { FileUtils.mkdir_p(model_dir) }

  after { FileUtils.rm_rf(library_path) }

  def archive_file(filename)
    create(:model_file, model: model, filename: filename, attachment: nil)
  end

  def build_zip(name, files)
    Zip::File.open(File.join(model_dir, name), create: true) do |zip|
      files.each { |path, data| zip.get_output_stream(path) { |f| f.write(data) } }
    end
  end

  def build_with_libarchive(name, compression, format, files)
    Archive::Writer.open_filename(File.join(model_dir, name), compression, format) do |writer|
      files.each do |path, data|
        writer.add_entry do |entry|
          entry.pathname = path
          entry.mode = 0o100644
          data
        end
      end
    end
  end

  def contents(name)
    out = {}
    Archive::Reader.open_filename(File.join(model_dir, name)) do |reader|
      reader.each_entry_with_data { |entry, data| out[entry.pathname] = data.is_a?(String) ? data : "" }
    end
    out
  end

  def sha(name)
    Digest::SHA512.file(File.join(model_dir, name)).hexdigest
  end

  def temp_files
    Dir.glob(File.join(model_dir, ".*.rewrite"))
  end

  it "removes the entry from a zip and keeps everything else" do
    build_zip("pack.zip", files)

    result = described_class.call(model_file: archive_file("pack.zip"), pathnames: ["pics/shot.png"])

    expect(result.status).to eq(:removed)
    expect(result.removed).to eq(["pics/shot.png"])
    expect(contents("pack.zip")).to eq("readme.txt" => "hello", "pics/other.png" => "other")
    expect(temp_files).to be_empty
  end

  it "rewrites a tar.gz in the same format and filter" do
    build_with_libarchive("pack.tar.gz", :gzip, :tar_pax_restricted, files)

    described_class.call(model_file: archive_file("pack.tar.gz"), pathnames: ["pics/shot.png"])

    expect(contents("pack.tar.gz").keys).to contain_exactly("readme.txt", "pics/other.png")
    Archive::Reader.open_filename(File.join(model_dir, "pack.tar.gz")) do |reader|
      reader.next_header
      expect(reader.compression).to eq(Archive::COMPRESSION_GZIP)
      expect(reader.format & Archive::FORMAT_BASE_MASK).to eq(Archive::FORMAT_TAR)
    end
  end

  it "rewrites a 7z archive" do
    build_with_libarchive("pack.7z", :none, :"7zip", files)

    described_class.call(model_file: archive_file("pack.7z"), pathnames: ["pics/shot.png"])

    expect(contents("pack.7z").keys).to contain_exactly("readme.txt", "pics/other.png")
  end

  it "removes several entries in one rewrite" do
    build_zip("pack.zip", files)

    result = described_class.call(model_file: archive_file("pack.zip"), pathnames: ["pics/shot.png", "pics/other.png"])

    expect(result.removed).to contain_exactly("pics/shot.png", "pics/other.png")
    expect(contents("pack.zip").keys).to eq(["readme.txt"])
  end

  it "leaves the archive untouched when none of the paths are present" do
    build_zip("pack.zip", files)
    before = sha("pack.zip")

    result = described_class.call(model_file: archive_file("pack.zip"), pathnames: ["missing.png"])

    expect(result.status).to eq(:noop)
    expect(sha("pack.zip")).to eq(before)
    expect(temp_files).to be_empty
  end

  it "leaves the original byte-identical when writing fails part-way" do
    build_zip("pack.zip", files)
    before = sha("pack.zip")
    allow_any_instance_of(Archive::Writer).to receive(:write_data).and_raise(Archive::Error, "disk full") # rubocop:disable RSpec/AnyInstance

    expect {
      described_class.call(model_file: archive_file("pack.zip"), pathnames: ["pics/shot.png"])
    }.to raise_error(Archive::Error)
    expect(sha("pack.zip")).to eq(before)
    expect(temp_files).to be_empty
  end

  it "leaves the original byte-identical when verification fails" do
    build_zip("pack.zip", files)
    before = sha("pack.zip")
    service = described_class.new(model_file: archive_file("pack.zip"), pathnames: ["pics/shot.png"])
    allow(service).to receive(:verify!).and_raise(described_class::VerifyFailed)

    expect { service.call }.to raise_error(described_class::VerifyFailed)
    expect(sha("pack.zip")).to eq(before)
    expect(temp_files).to be_empty
  end

  it "reports non-filesystem libraries as unwritable without touching anything" do
    build_zip("pack.zip", files)
    before = sha("pack.zip")
    file = archive_file("pack.zip")
    allow(file.model.library).to receive(:storage_service).and_return("s3")

    expect(described_class.writable?(file)).to be false
    expect(described_class.call(model_file: file, pathnames: ["pics/shot.png"]).status).to eq(:unwritable)
    expect(sha("pack.zip")).to eq(before)
  end

  it "reports an archive libarchive cannot read back as unwritable" do
    File.binwrite(File.join(model_dir, "pack.rar"), "Rar!\x1A\x07\x00not really a rar".b)

    expect(described_class.writable?(archive_file("pack.rar"))).to be false
  end

  it "keeps the original file mode" do
    build_zip("pack.zip", files)
    File.chmod(0o640, File.join(model_dir, "pack.zip"))

    described_class.call(model_file: archive_file("pack.zip"), pathnames: ["pics/shot.png"])

    expect(File.stat(File.join(model_dir, "pack.zip")).mode & 0o777).to eq(0o640)
  end
end
