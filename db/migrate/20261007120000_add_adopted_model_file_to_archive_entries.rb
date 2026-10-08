# INIT-001/SPEC-001: link an archive image entry to the ModelFile adopted from it.
class AddAdoptedModelFileToArchiveEntries < ActiveRecord::Migration[8.0]
  def change
    add_reference :archive_entries, :adopted_model_file,
      null: true,
      index: true,
      foreign_key: {to_table: :model_files, on_delete: :nullify}
  end
end
