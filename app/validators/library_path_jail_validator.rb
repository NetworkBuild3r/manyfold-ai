# frozen_string_literal: true

class LibraryPathJailValidator < ActiveModel::EachValidator
  def validate_each(record, attribute, value)
    return if value.nil?

    # Ruby 3.4+ File.join strips a leading separator from later args, so absolute
    # filenames must be rejected on the attribute itself before joining.
    if LibraryPathJail.unsafe_relative?(value)
      record.errors.add attribute, :outside_library
      return
    end

    model = record.model
    library = model&.library
    return if model.nil? || library.nil? || library.path.blank?

    relative = File.join(model.path.to_s, value.to_s)
    return if LibraryPathJail.within?(library.path, relative)

    record.errors.add attribute, :outside_library
  end
end
