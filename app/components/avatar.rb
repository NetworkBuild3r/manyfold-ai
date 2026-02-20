# frozen_string_literal: true

class Components::Avatar < Components::Base
  def initialize(url:, size: nil)
    @url = url
    @size = size
  end

  def view_template
    size_class = case @size
    when :large then "w-16 h-16"
    when :small then "w-8 h-8"
    else "w-10 h-10"
    end
    img src: @url, class: "rounded-full object-cover #{size_class}"
  end
end
