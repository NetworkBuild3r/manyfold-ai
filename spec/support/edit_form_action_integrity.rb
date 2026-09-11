# frozen_string_literal: true

# INIT-027/SPEC-013 — HTML5 parse so nested <form> is not silently ignored.
module EditFormActionIntegrity
  def html5_document(html = response.body)
    Nokogiri::HTML5.parse(html)
  end

  def forms_targeting(path, html: response.body)
    html5_document(html).css("form").select do |form|
      action = form["action"].to_s.split("?").first
      action.end_with?(path)
    end
  end

  def method_overrides(form)
    form.css('input[name="_method"]').map { |input| input["value"].to_s.downcase }
  end
end

RSpec.configure do |config|
  config.include EditFormActionIntegrity, type: :request
end
