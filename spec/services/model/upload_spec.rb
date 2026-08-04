# frozen_string_literal: true

require "rails_helper"

# INIT-022/SPEC-001 — regression: dummy Model must not receive Sidekiq-only owner_id.
RSpec.describe Model::Upload do
  subject(:result) { described_class.call(library: library, params: params, owner: owner, enqueue: enqueue) }

  let(:library) { create(:library) }
  let(:owner) { create(:contributor) }
  let(:enqueue) { true }
  let(:params) {
    {
      name: "Test Upload Model",
      license: "MIT",
      sensitive: "0",
      tag_list: ["tag1"],
      permission_preset: "public",
      file: {
        "0" => {
          id: "upload_key",
          name: "test.stl"
        }
      }
    }
  }

  describe ".call" do
    it "does not raise UnknownAttributeError for owner_id on the validation dummy" do
      expect { result }.not_to raise_error
    end

    it "builds a valid single-upload dummy without owner_id column attrs" do
      expect(result.valid?).to be true
      expect(result.model).to be_a(Model)
      expect(result.model.has_attribute?(:owner_id)).to be false
    end

    it "keeps owner_id in job_options for ProcessUploadedFileJob" do
      expect(result.job_options).to include(owner_id: owner.id)
    end

    it "enqueues ProcessUploadedFileJob with owner_id" do
      expect { result }
        .to have_enqueued_job(ProcessUploadedFileJob)
        .with(
          library.id,
          [{
            id: "upload_key",
            storage: "cache",
            metadata: {filename: "test.stl"}
          }],
          hash_including(owner_id: owner.id, name: "Test Upload Model", permission_preset: "public")
        ).once
    end

    context "with multiple archives (multi_upload)" do
      let(:params) {
        {
          license: "MIT",
          sensitive: "0",
          file: {
            "0" => {id: "upload_1", name: "test.zip"},
            "1" => {id: "upload_2", name: "example.zip"}
          }
        }
      }

      it "does not raise UnknownAttributeError for owner_id" do
        expect { result }.not_to raise_error
        expect(result.valid?).to be true
        expect(result.multiple?).to be true
      end

      it "still enqueues jobs with owner_id" do
        expect { result }
          .to have_enqueued_job(ProcessUploadedFileJob)
          .with(library.id, anything, hash_including(owner_id: owner.id))
          .exactly(2).times
      end
    end

    context "when enqueue is false" do
      let(:enqueue) { false }

      it "returns job_options including owner_id without enqueuing" do
        expect { result }.not_to have_enqueued_job(ProcessUploadedFileJob)
        expect(result.job_options[:owner_id]).to eq(owner.id)
      end
    end
  end
end
