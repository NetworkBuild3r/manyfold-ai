# frozen_string_literal: true

class Components::Avatar < Components::Base
  def initialize(url:, size: nil)
    @url = url
    @size = size
  end

  def view_template
    size_class = case @size
    when :large then "tw:w-16 tw:h-16"
    when :small then "tw:w-8 tw:h-8"
    else "tw:w-10 tw:h-10"
    end
    img src: @url, class: "tw:rounded-full tw:object-cover #{size_class}"
  end
end
