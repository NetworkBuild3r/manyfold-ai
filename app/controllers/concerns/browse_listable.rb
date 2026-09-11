# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
# INIT-027/SPEC-009 — shared tag/window/count helpers. Index actions stay split:
# creators apply `@filter.creators(scope, @models)` while collections apply
# `@filter.collections(scope)`; includes and count FKs also differ. A unified
# `index` would hide those and is worse than the remaining per-action lines.
module BrowseListable
  extend ActiveSupport::Concern

  included do
    include BrowseWindowable
  end

  private

  def prepare_browse_page(scope)
    prepare_browse_window(scope)
  end

  def prepare_browse_index_tags
    @tags, @unrelated_tag_count = generate_tag_list(@models, @filter.tags)
    @tags, @kv_tags = split_key_value_tags(@tags)
    @unrelated_tag_count = nil unless @filter.any?
  end

  def grouped_policy_count(relation, column, ids)
    ids.empty? ? {} : relation.where(column => ids).group(column).count
  end
end
