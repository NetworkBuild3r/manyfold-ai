# frozen_string_literal: true

class MakePublicIDsLowercase < ActiveRecord::Migration[7.2]
  MODELS = [Collection, Comment, Creator, Library, ModelFile, Model, User].freeze

  def up
    MODELS.each do |it|
      it.update_all("public_id = lower(public_id)") # rubocop:disable Rails/SkipsModelValidations
    end
    return unless connection.table_exists?(:problems) && connection.column_exists?(:problems, :public_id)
    connection.execute("UPDATE problems SET public_id = lower(public_id)")
  end

  def down
  end
end
