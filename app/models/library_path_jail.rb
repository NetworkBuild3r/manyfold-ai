# frozen_string_literal: true

# INIT-019/SPEC-002 — keep storage keys and filenames under File.expand_path(library.path)
module LibraryPathJail
  class EscapeError < StandardError; end

  module_function

  # True when relative_path expands inside library_path (separator-suffix, not bare start_with?).
  def within?(library_path, relative_path)
    return false if library_path.blank?
    return false if unsafe_relative?(relative_path)

    root = File.expand_path(library_path.to_s)
    candidate = File.expand_path(relative_path.to_s, root)
    contained?(root, candidate)
  end

  # Returns relative_path when jailed; raises EscapeError when it would leave the library.
  def assert_within!(library_path, relative_path)
    raise EscapeError, "path escapes library root" unless within?(library_path, relative_path)

    relative_path
  end

  def assert_safe_relative!(relative_path)
    raise EscapeError, "unsafe relative path" if unsafe_relative?(relative_path)

    relative_path
  end

  # Reject .. segments, absolute paths, NUL, and blank after normalize.
  def unsafe_relative?(relative_path)
    s = relative_path.to_s
    return true if s.empty?
    return true if s.include?("\0")
    return true if absolute_path?(s)

    normalized = s.tr("\\", "/")
    normalized.split("/").any?("..")
  end

  def contained?(library_root, absolute_candidate)
    root = File.expand_path(library_root.to_s)
    candidate = File.expand_path(absolute_candidate.to_s)
    return true if candidate == root

    candidate.start_with?(root + File::SEPARATOR)
  end

  def absolute_path?(path)
    s = path.to_s
    s.start_with?("/") || s.match?(/\A[A-Za-z]:[\\\/]/)
  end
  private_class_method :absolute_path?
end
