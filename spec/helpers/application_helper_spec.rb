require "rails_helper"

RSpec.describe ApplicationHelper do
  describe "#icon" do
    it "returns the correct HTML for the icon" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
      html = helper.Icon(icon: "test", label: "Test Label")
      doc = Nokogiri::HTML(html)
      expect(doc.at("i")["class"]).to eq("bi bi-test text-current")
      expect(doc.at("i")["role"]).to eq("img")
      expect(doc.at("i")["title"]).to eq("Test Label")
    end

    it "supports RPG-awesome icons" do
      html = helper.Icon(icon: "ra-test", label: "Test Label")
      doc = Nokogiri::HTML(html)
      expect(doc.at("i")["class"]).to eq("ra ra-test text-current")
    end
  end

  describe "#card" do
    it "returns the correct HTML for the card" do # rubocop:todo RSpec/MultipleExpectations
      html = helper.card("test", "Test Title") { "Test Content" }
      doc = Nokogiri::HTML(html)
      expect(doc.at("div[class*='rounded-xl']")["class"]).to include("rounded-xl", "mb-4")
      expect(doc.at("div[class*='text-white']")["class"]).to include("text-white")
      expect(doc.text).to include("Test Content")
    end
  end

  describe "#text_input_row" do
    it "returns the correct HTML for the text input row" do # rubocop:todo RSpec/MultipleExpectations
      form = ActionView::Helpers::FormBuilder.new(:test, nil, helper, {})
      html = helper.text_input_row(form, :field)
      doc = Nokogiri::HTML(html)
      expect(doc.at("input")["class"]).to include("rounded-lg")
    end
  end

  describe "#rich_text_input_row" do
    it "returns the correct HTML for the rich text input row" do # rubocop:todo RSpec/MultipleExpectations
      form = ActionView::Helpers::FormBuilder.new(:test, nil, helper, {})
      html = helper.rich_text_input_row(form, :field)
      doc = Nokogiri::HTML(html)
      expect(doc.at("textarea")["class"]).to include("rounded-lg")
    end
  end

  describe "#nav_link" do
    it "returns the correct HTML for the navigation link" do # rubocop:todo RSpec/MultipleExpectations
      html = helper.nav_link("test", "Test Text", "/")
      doc = Nokogiri::HTML(html)
      expect(doc.at("a")["class"]).to include("rounded-lg")
      expect(doc.css("span")[1].text).to eq("Test Text")
    end
  end

  describe "#settings_nav_link_class" do
    it "returns active state classes when on the given path" do
      allow(helper).to receive(:current_page?).with("/settings").and_return(true)
      result = helper.settings_nav_link_class("/settings")
      expect(result).to include("bg-primary-100", "font-medium")
    end

    it "returns inactive state classes when not on the given path" do
      allow(helper).to receive(:current_page?).with("/settings").and_return(false)
      result = helper.settings_nav_link_class("/settings")
      expect(result).to include("text-secondary-700", "hover:bg-secondary-100")
      expect(result).not_to include("bg-primary-100")
    end
  end

  describe "#tour_state" do
    it "handles nil tour state in database" do
      user = instance_double(User)
      allow(user).to receive_messages(first_use?: false, tour_state: nil)
      allow(helper).to receive(:current_user).and_return(user)
      attrs = helper.tour_attributes(id: "id", title: "title", description: "description")
      expect(attrs["tour-id-completed"]).to eq "false"
    end

    it "handles empty tour state in database" do
      user = instance_double(User)
      allow(user).to receive_messages(first_use?: false, tour_state: {})
      allow(helper).to receive(:current_user).and_return(user)
      attrs = helper.tour_attributes(id: "id", title: "title", description: "description")
      expect(attrs["tour-id-completed"]).to eq "false"
    end

    it "matches completed tour states" do
      user = instance_double(User)
      allow(user).to receive_messages(first_use?: false, tour_state: {"completed" => ["id"]})
      allow(helper).to receive(:current_user).and_return(user)
      attrs = helper.tour_attributes(id: "id", title: "title", description: "description")
      expect(attrs["tour-id-completed"]).to eq "true"
    end
  end

  describe "#button_class_for" do
    it "joins BASE_CLASSES with the named variant" do
      expect(helper.button_class_for("primary")).to include(Components::BaseButton::BASE_CLASSES)
      expect(helper.button_class_for("primary")).to include(Components::BaseButton::VARIANT_CLASSES.fetch("primary"))
    end

    it "does not double-prefix toolbar" do
      expect(helper.button_class_for("toolbar")).to eq(Components::BaseButton::VARIANT_CLASSES.fetch("toolbar"))
    end
  end

  describe "#input_class" do
    it "equals TextInputRow::INPUT_CLASS" do
      expect(helper.input_class).to eq(Components::TextInputRow::INPUT_CLASS)
    end
  end

  describe "#secondary_action_class" do
    it "equals the named toolbar VARIANT_CLASSES entry byte-for-byte" do
      expect(helper.secondary_action_class).to eq(Components::BaseButton::VARIANT_CLASSES.fetch("toolbar"))
    end
  end

  # INIT-027/SPEC-005 — links stay on primary-* so the CSS accent alias applies.
  describe "#content_link_class" do
    it "uses primary text tokens (light and dark)" do
      expect(helper.content_link_class).to include("text-primary-700")
      expect(helper.content_link_class).to include("dark:text-primary-400")
    end
  end

  # INIT-028/SPEC-003 — D-9: SSR .dark follows ThemeResolver, not raw SiteSettings.
  describe "#dark_theme?" do
    before { allow(helper).to receive(:current_user).and_return(nil) }

    it "is true when the resolver returns dark" do
      allow(ThemeResolver).to receive(:call).with(user: nil).and_return("dark")
      expect(helper.dark_theme?).to be true
    end

    it "is false when the resolver returns light" do
      allow(ThemeResolver).to receive(:call).with(user: nil).and_return("light")
      expect(helper.dark_theme?).to be false
    end

    it "is false when the resolver returns system" do
      allow(ThemeResolver).to receive(:call).with(user: nil).and_return("system")
      expect(helper.dark_theme?).to be false
    end

    it "passes current_user into ThemeResolver" do
      user = instance_double(User)
      allow(helper).to receive(:current_user).and_return(user)
      allow(ThemeResolver).to receive(:call).with(user: user).and_return("light")
      expect(helper.resolved_theme).to eq "light"
    end
  end

  describe "#file_input_row" do
    it "uses TextInputRow::INPUT_CLASS on the file field" do
      form = ActionView::Helpers::FormBuilder.new(:test, nil, helper, {})
      html = helper.file_input_row(form, :avatar)
      expect(html).to include(Components::TextInputRow::INPUT_CLASS)
    end
  end

  describe "#errors_for" do
    it "delegates message text to InputRow.messages_for" do
      record = User.new
      record.errors.add(:email, "is invalid")
      expect(helper.errors_for(record, :email)).to include(Components::InputRow.messages_for(record, :email))
      expect(helper.errors_for(record, :email)).to include(Components::InputRow::ERROR_CLASS)
    end
  end
end
