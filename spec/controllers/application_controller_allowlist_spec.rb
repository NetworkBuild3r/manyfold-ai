# frozen_string_literal: true

require "rails_helper"

# INIT-019/SPEC-007
RSpec.describe ApplicationController do
  def resolve(name)
    controller = described_class.new
    allow(controller).to receive(:params).and_return(
      ActionController::Parameters.new(commentable_class: name)
    )
    controller.send(:resolve_allowed_class!, :commentable_class)
  end

  it "rejects Kernel" do
    expect { resolve("Kernel") }.to raise_error(ActionController::BadRequest)
  end

  it "rejects User" do
    expect { resolve("User") }.to raise_error(ActionController::BadRequest)
  end

  it "allows Model" do
    expect(resolve("Model")).to eq(Model)
  end
end
