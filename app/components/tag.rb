# frozen_string_literal: true

class Components::Tag < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  CLASSES = "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-secondary-200 text-secondary-800 dark:bg-secondary-600 dark:text-secondary-200 no-underline hover:opacity-90".freeze

  def initialize(tag:, show_count: false, filters: {}, html_options: {}, filter_in_place: false)
    @tag = tag
    @show_count = show_count
    @filter_in_place = filter_in_place
    @filters = filters || {}
    @filters[:tag] ||= []
    @html_options = html_options.merge({class: CLASSES})
  end

  def view_template
    new_filters = @filters.merge(tag: @filters[:tag] | [@tag.name])
    span itemprop: "keywords" do
      link_to (@filter_in_place ? new_filters : models_path(new_filters)), @html_options do
        parts = [@tag.name]
        parts << "(#{@tag.taggings_count})" if @show_count
        parts.join " "
      end
    end
  end
end
