module Lister
  extend ActiveSupport::Concern

  included do
    acts_as_favoritor
  end

  def list(object, list_name)
    favorite(object, scope: list_name)
    clear_personal_list_caches!
  end

  def delist(object, list_name)
    unfavorite(object, scope: list_name)
    clear_personal_list_caches!
  end

  def set_list_state(object, list_name, listed)
    if listed
      list(object, list_name)
    else
      delist(object, list_name)
    end
  end

  def listed?(object, list_name)
    favorited?(object, scope: list_name)
  end

  def clear_personal_list_caches!
    @favorited_model_ids = nil
    @queued_model_ids = nil
    @printed_model_ids = nil
  end
end
