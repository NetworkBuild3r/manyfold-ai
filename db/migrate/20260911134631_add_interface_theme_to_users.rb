# frozen_string_literal: true

# INIT-028/SPEC-002 — nullable per-user overlay; NULL inherits instance theme (ADR D-2).
class AddInterfaceThemeToUsers < ActiveRecord::Migration[8.0]
  def change
    add_column :users, :interface_theme, :string
  end
end
