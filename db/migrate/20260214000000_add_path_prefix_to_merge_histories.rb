# frozen_string_literal: true

class AddPathPrefixToMergeHistories < ActiveRecord::Migration[8.0]
  def change
    add_column :merge_histories, :path_prefix, :string, if_not_exists: true
  end
end
