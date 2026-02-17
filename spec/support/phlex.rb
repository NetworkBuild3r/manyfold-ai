# Controller for component specs - includes Pundit so policy helper exists
class ComponentSpecController < ActionView::TestCase::TestController
  include Pundit::Authorization
end

module PhlexTestHelpers
  def render(...)
    view_context.render(...)
  end

  delegate :view_context, to: :controller

  def controller
    @controller ||= ComponentSpecController.new
  end

  def sign_in(user)
    allow(controller).to receive(:current_user).and_return(user)
  end
end

RSpec.configure do |config|
  config.include PhlexTestHelpers, type: :component
end
