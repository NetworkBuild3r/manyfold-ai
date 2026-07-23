# frozen_string_literal: true

# Application-layer delete for Model — cascade nested models, clear tags without
# re-running publish validations, then remove storage + DB row.
class Model::Delete
  def self.call(model)
    new(model).call
  end

  def self.delete_without_cascade(model)
    model.skip_problem_check = true
    # Remove all presupported_version relationships first, they get in the way
    model.model_files.update_all(presupported_version_id: nil) # rubocop:disable Rails/SkipsModelValidations
    model.model_files.each(&:delete_from_disk_and_destroy)
    # Do not use update!(tags: []) — public models missing license/creator fail
    # validate_publishable and surface a misleading 422 "rejected" page.
    model.taggings.delete_all
    model.library.storage.delete_prefixed(model.path)
    model.destroy
  end

  def initialize(model)
    @model = model
  end

  def call
    @model.skip_problem_check = true

    Current.set(skip_problem_checks: true) do
      @model.contained_models.order(Arel.sql("LENGTH(#{Model.quoted_table_name}.path) DESC")).to_a.each do |child|
        self.class.delete_without_cascade(child)
      end
      self.class.delete_without_cascade(@model)
    end
  end
end
