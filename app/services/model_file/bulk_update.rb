# frozen_string_literal: true

class ModelFile::BulkUpdate
  Result = Data.define(:split_model)

  def self.call(model:, files:, attributes:, user:, printed:, pattern: nil, replacement: nil, split: false)
    new(model: model, files: files, attributes: attributes, user: user, printed: printed, pattern: pattern, replacement: replacement, split: split).call
  end

  def initialize(model:, files:, attributes:, user:, printed:, pattern: nil, replacement: nil, split: false)
    @model = model
    @files = files
    @attributes = attributes
    @user = user
    @printed = printed
    @pattern = pattern
    @replacement = replacement
    @split = split
  end

  def call
    @files.each do |file|
      ActiveRecord::Base.transaction do
        @user.set_list_state(file, :printed, @printed === "1")
        options = {}
        if @pattern.present?
          options[:filename] =
            file.filename.split(file.extension).first.gsub(@pattern, @replacement) +
            file.extension
        end
        file.update(@attributes.merge(options))
      end
    end

    split_model = @split ? @model.split!(files: @files) : nil
    Result.new(split_model: split_model)
  end
end
