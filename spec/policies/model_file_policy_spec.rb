require "rails_helper"

describe ModelFilePolicy do
  subject(:policy) { described_class }

  let(:model) { create(:model) }
  let(:previewable_file) { create(:model_file, model: model, previewable: true) }
  let(:private_file) { create(:model_file, model: model) }
  let(:member) { create(:user) }

  permissions :show? do
    context "with public preview permission granted" do
      before do
        model.grant_permission_to "preview", nil
      end

      it "shows previewable file" do
        expect(policy).to permit(nil, previewable_file)
      end

      it "doesn't show private file" do
        expect(policy).not_to permit(nil, private_file)
      end
    end

    context "with no public permission granted" do
      it "doesn't show previewable file" do
        expect(policy).not_to permit(nil, previewable_file)
      end

      it "doesn't show private file" do
        expect(policy).not_to permit(nil, private_file)
      end
    end
  end

  permissions :download? do
    context "with preview granted only" do
      before do
        model.revoke_all_permissions(Role.find_by!(name: :member))
        model.grant_permission_to "preview", member
      end

      it "does not allow download of a previewable archive file" do
        expect(policy).not_to permit(member, previewable_file)
      end
    end

    context "with view granted" do
      before do
        model.revoke_all_permissions(Role.find_by!(name: :member))
        model.grant_permission_to "view", member
      end

      it "allows download" do
        expect(policy).to permit(member, previewable_file)
      end
    end
  end
end
