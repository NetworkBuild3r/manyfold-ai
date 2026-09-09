# frozen_string_literal: true

# Merge source into target, then apply the operator's A/B/override field picks.
# Snapshots are taken first because Model::Merge destroys the source model.
class Model::MergeWithChoices
  FIELD_KEYS = %w[name caption notes creator_id collection_id license sensitive indexable preview].freeze

  def self.call(target:, source:, choices:, overrides: {}, tag_strategy: "combine")
    new(
      target: target,
      source: source,
      choices: choices,
      overrides: overrides,
      tag_strategy: tag_strategy
    ).call
  end

  def initialize(target:, source:, choices:, overrides:, tag_strategy:)
    @target = target
    @source = source
    @choices = (choices || {}).stringify_keys
    @overrides = (overrides || {}).stringify_keys
    @tag_strategy = tag_strategy.to_s
  end

  def call
    target_snap = snapshot(@target)
    source_snap = snapshot(@source)
    Model::Merge.call(@target, @source)
    @target.reload
    apply_fields(target_snap, source_snap)
    apply_tags(target_snap, source_snap)
    @target.save!
    @target
  end

  private

  def snapshot(model)
    {
      name: model.name,
      caption: model.caption,
      notes: model.notes,
      creator_id: model.creator_id,
      collection_id: model.collection_id,
      license: model.license,
      sensitive: model.sensitive,
      indexable: model.indexable,
      tag_list: model.tag_list.to_a,
      preview_file_id: model.preview_file_id,
      preview_digest: model.preview_file&.digest,
      preview_filename: model.preview_file&.filename
    }
  end

  def apply_fields(target_snap, source_snap)
    FIELD_KEYS.each do |key|
      side = @choices[key].presence || "a"
      if key == "preview"
        apply_preview(target_snap, source_snap, side)
        next
      end
      @target.public_send(:"#{key}=", value_for(key, side, target_snap, source_snap))
    end
  end

  def value_for(key, side, target_snap, source_snap)
    if side == "override"
      return override_value(key)
    end

    snap = (side == "b") ? source_snap : target_snap
    snap[key.to_sym]
  end

  def override_value(key)
    raw = @overrides[key]
    case key
    when "sensitive"
      ActiveModel::Type::Boolean.new.cast(raw)
    when "indexable"
      (raw == "inherit") ? nil : raw
    when "creator_id", "collection_id"
      raw.presence
    else
      raw
    end
  end

  def apply_preview(target_snap, source_snap, side)
    chosen = (side == "b") ? source_snap : target_snap
    return if chosen[:preview_file_id].blank?

    file = @target.model_files.find_by(id: chosen[:preview_file_id]) ||
      @target.model_files.find_by(digest: chosen[:preview_digest]) ||
      @target.model_files.find_by(filename: chosen[:preview_filename])
    @target.preview_file = file if file
  end

  def apply_tags(target_snap, source_snap)
    tags = case @tag_strategy
    when "a" then target_snap[:tag_list]
    when "b" then source_snap[:tag_list]
    else (target_snap[:tag_list] + source_snap[:tag_list]).uniq
    end
    @target.tag_list = tags
  end
end
