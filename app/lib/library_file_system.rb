# frozen_string_literal: true

# Filesystem storage that never chmods after a move/copy.
# Synology NFS root-squash maps the pod's root to nobody, so Shrine's default
# `chmod 0644` after FileUtils.mv raises Errno::EPERM and 500s a merge.
class LibraryFileSystem < Shrine::Storage::FileSystem
  def initialize(directory, **options)
    super(directory, **options.merge(permissions: nil, directory_permissions: nil))
  end

  private

  def move(io, path)
    source = io.respond_to?(:path) ? io.path : io.storage.path(io.id)
    File.rename(source, path)
  rescue SystemCallError
    FileUtils.cp(source, path)
    File.unlink(source)
    if io.is_a?(Shrine::UploadedFile) && io.storage.is_a?(Shrine::Storage::FileSystem) && io.storage.clean?
      io.storage.clean(io.storage.path(io.id))
    end
  end
end
