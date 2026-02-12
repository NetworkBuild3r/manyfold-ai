module ApplicationHelper
  def dark_theme?
    SiteSettings.validated_theme == "dark"
  end

  def site_name(default: translate("application.title"))
    SiteSettings.site_name.presence || default
  end

  def site_tagline
    SiteSettings.site_tagline.presence || t("application.tagline")
  end

  def site_icon
    SiteSettings.site_icon.presence || "roundel.svg"
  end

  def checkmark(value)
    value ? "✅" : "❌"
  end

  def client_os
    user_agent = UserAgentParser.parse(request&.user_agent)
    user_agent&.os
  end

  def icon_for(klass)
    case klass.name
    when "Creator"
      "person"
    when "Collection"
      "collection"
    when "Library"
      "boxes"
    when "Model"
      "box"
    when "ModelFile"
      "file"
    when "User"
      "person"
    end
  end

  def markdownify(text)
    Kramdown::Document.new(
      sanitize(text),
      header_offset: 2,
      input: "GFM"
    ).to_html.html_safe # rubocop:disable Rails/OutputSafety
  end

  def card(style, title = nil, options = {}, &content)
    id = options[:id] || "card-#{SecureRandom.hex(4)}"
    card_class = ["tw:rounded-xl", "tw:border", "tw:border-secondary-200", "tw:dark:border-secondary-600", "tw:bg-white", "tw:dark:bg-secondary-800", "tw:shadow-sm", "tw:mb-4", options[:class]].compact.join(" ")
    card_class += " skip-link-container" if options[:skip_link]
    card_data = options[:data] || {}
    card_data = card_data.merge(controller: "collapse") if options[:collapse]
    tag.div class: card_class, data: card_data, id: id do
      safe_join([
        if title.present?
          header_bg = style.to_s == "primary" ? "tw:bg-primary-600" : "tw:bg-secondary-600"
          tag.div(class: "tw:px-4 tw:py-3 tw:text-white tw:rounded-t-xl #{header_bg} tw:relative") do
            if options[:collapse]
              safe_join([
                tag.div(class: "tw:flex tw:items-center tw:justify-between tw:relative tw:z-10") do
                  safe_join([title, tag.span(Icon(icon: "arrows-expand", label: t("general.expand")), class: "tw:md:hidden")])
                end,
                tag.a(
                  nil,
                  class: "tw:md:hidden tw:absolute tw:inset-0 tw:z-0 tw:block",
                  "data-action": "click->collapse#toggle",
                  "aria-expanded": false,
                  "aria-controls": "#{id}-collapse",
                  "aria-label": t("general.expand")
                )
              ])
            else
              title
            end
          end
        end,
        (skip_link(options[:skip_link][:target], options[:skip_link][:text]) if options[:skip_link]),
        tag.div(
          class: ["tw:p-4", ("collapse-md" if options[:collapse] == "md")].compact.join(" "),
          id: "#{id}-collapse",
          data: (options[:collapse] ? { collapse_target: "content" } : {})
        ) do
          tag.div do
            yield
          end
        end
      ].compact)
    end
  end

  def text_input_row(form, attribute, options = {})
    TextInputRow(
      form: form,
      attribute: attribute,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def password_input_row(form, attribute, options = {})
    PasswordInputRow(
      form: form,
      attribute: attribute,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def url_input_row(form, attribute, options = {})
    UrlInputRow(
      form: form,
      attribute: attribute,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def numeric_input_row(form, attribute, options = {})
    NumericInputRow(
      form: form,
      attribute: attribute,
      unit: options.delete(:unit),
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def rich_text_input_row(form, attribute, options = {})
    RichTextInputRow(
      form: form,
      attribute: attribute,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def checkbox_input_row(form, attribute, options = {})
    CheckBoxInputRow(
      form: form,
      attribute: attribute,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def select_input_row(form, attribute, select_options, options = {})
    SelectInputRow(
      form: form,
      attribute: attribute,
      select_options: select_options,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def collection_select_input_row(form, attribute, collection, value_method, text_method, options = {})
    CollectionSelectInputRow(
      form: form,
      attribute: attribute,
      collection: collection,
      value_method: value_method,
      text_method: text_method,
      label: options.delete(:label),
      help: options.delete(:help),
      options: options
    )
  end

  def file_input_row(form, name, options = {})
    input_class = "tw:block tw:w-full tw:rounded-lg tw:border tw:border-secondary-300 tw:px-3 tw:py-2 tw:shadow-sm tw:focus:ring-2 tw:focus:ring-primary-500 tw:dark:border-secondary-600 tw:dark:bg-secondary-800"
    safe_join([
      content_tag(:div) do
        form.label(name, options[:label], class: "tw:block tw:text-sm tw:font-medium tw:text-secondary-700 tw:dark:text-secondary-300")
      end,
      content_tag(:div, class: "tw:mt-1") do
        safe_join [
          content_tag(:div, class: "tw:flex tw:gap-2 tw:items-center") do
            safe_join [
              form.file_field(name, class: input_class),
              options[:remove] ? form.check_box(:"remove_#{name}", class: "tw:rounded tw:border-secondary-300 tw:text-primary-600 tw:focus:ring-primary-500 tw:h-4 tw:w-4", autocomplete: "off") : nil,
              options[:remove] ? form.label(:"remove_#{name}", Icon(icon: "trash", label: options[:remove_label]), class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:border tw:border-danger tw:text-danger tw:bg-transparent tw:hover:bg-danger/10 tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:cursor-pointer") : nil
            ].compact
          end,
          errors_for(form.object, name),
          (options[:help] ? content_tag(:span, class: "tw:text-sm tw:text-secondary-500 tw:dark:text-secondary-400 tw:mt-1 tw:block") { options[:help] } : nil)
        ].compact
      end
    ])
  end

  def nav_link(ico, text, path, options = {})
    link_class = if options[:style].present?
      options[:style]
    else
      base = "tw:flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-2 tw:rounded-lg tw:text-white/90 tw:hover:text-white tw:hover:bg-primary-500 tw:no-underline tw:transition-colors focus-visible:tw:ring-2 focus-visible:tw:ring-white focus-visible:tw:ring-offset-2 focus-visible:tw:ring-offset-primary-600"
      base += " tw:bg-primary-500 tw:text-white" if current_page?(path)
      base
    end
    aria = {label: options[:aria_label]}
    aria[:current] = "page" if !options[:style].present? && current_page?(path)
    link_to(
      safe_join(
        [
          content_tag(:span, Icon(icon: ico, label: options[:title].presence || text), class: options[:icon_style]),
          content_tag(:span, text, class: options[:text_style])
        ],
        " "
      ),
      path,
      class: link_class,
      method: options[:method],
      rel: options[:nofollow] ? "nofollow" : nil,
      id: options[:id],
      data: options[:data],
      aria: aria
    )
  end

  def errors_for(record, attribute)
    return if record.nil? || attribute.nil?
    return unless record.errors.include? attribute
    content_tag(:div,
      record.errors.full_messages_for(attribute).join("; "),
      class: "tw:text-danger tw:text-sm tw:mt-1 tw:block")
  end

  def skip_link(target, text)
    content_tag :div, class: "tw:max-w-screen-2xl tw:mx-auto tw:px-4 tw:py-2 tw:bg-primary-600 tw:text-white focus-within:tw:ring-2 focus-within:tw:ring-primary-400" do
      link_to text, "##{target}", class: "tw:text-white tw:no-underline focus:tw:underline tw:outline-none", tabindex: 0
    end
  end

  def translate_with_locale_wrapper(key, **options)
    translate(key, **options) do |str, _key|
      str&.locale ? content_tag(:span, lang: str.locale) { sanitize str } : str
    end
  end
  alias_method :t, :translate_with_locale_wrapper

  def pagination_settings
    current_user&.pagination_settings || SiteSettings::UserDefaults::PAGINATION
  end

  # Returns an array of active filter entries for pills and sidebar. Each entry is a hash with:
  # :key, :icon, :type_label, :value_html, :remove_url, :aria_remove, :pill_label
  # Reused by models list (Phase 5) and creators/collections index (Phase 7).
  def active_filters_list(filter)
    return [] if filter.blank? || !filter.any?

    base_params = filter.to_params
    entries = []

    if filter.filtering_by?(:q)
      q = filter.parameter(:q)
      entries << {
        key: :q,
        icon: "search",
        type_label: t("application.filters_card.search"),
        value_html: q,
        remove_url: url_for(base_params.except(:q)),
        aria_remove: t("application.filters_card.remove_search_filter"),
        pill_label: "#{t("application.filters_card.search")}: #{q}"
      }
    end

    if filter.filtering_by?(:collection)
      coll = filter.collection
      val = coll ? link_to(coll.name, {collection: filter.collection}) : t("application.filters_card.unknown")
      entries << {
        key: :collection,
        icon: "collection",
        type_label: Collection.model_name.human,
        value_html: val,
        remove_url: url_for(base_params.except(:collection)),
        aria_remove: t("application.filters_card.remove_collection_filter"),
        pill_label: "#{Collection.model_name.human}: #{coll&.name || t("application.filters_card.unknown")}"
      }
    end

    if filter.filtering_by?(:library)
      libs = [*filter.parameter(:library)].map { |l| Library.find_param(l).name }.join(", ")
      entries << {
        key: :library,
        icon: "boxes",
        type_label: Library.model_name.human,
        value_html: libs,
        remove_url: url_for(base_params.except(:library)),
        aria_remove: t("application.filters_card.remove_library_filter"),
        pill_label: "#{Library.model_name.human}: #{libs}"
      }
    end

    if filter.filtering_by?(:creator)
      cr = filter.creator
      val = cr ? link_to(cr.name.careful_titleize, cr) : t("application.filters_card.unknown")
      entries << {
        key: :creator,
        icon: "person",
        type_label: Creator.model_name.human,
        value_html: val,
        remove_url: url_for(base_params.except(:creator)),
        aria_remove: t("application.filters_card.remove_creator_filter"),
        pill_label: "#{Creator.model_name.human}: #{cr&.name&.careful_titleize || t("application.filters_card.unknown")}"
      }
    end

    if filter.filtering_by?(:owner)
      entries << {
        key: :owner,
        icon: "person",
        type_label: t("application.filters_card.owner"),
        value_html: filter.owner.username,
        remove_url: url_for(base_params.except(:owner)),
        aria_remove: t("application.filters_card.remove_owner_filter"),
        pill_label: "#{t("application.filters_card.owner")}: #{filter.owner.username}"
      }
    end

    if filter.filtering_by?(:tag)
      entries << {
        key: :tag,
        icon: "tag",
        type_label: ActsAsTaggableOn::Tag.model_name.human(count: 100),
        value_html: nil, # sidebar renders application/tag_list for this row
        remove_url: url_for(base_params.except(:tag)),
        aria_remove: t("application.filters_card.remove_tag_filter"),
        pill_label: "#{ActsAsTaggableOn::Tag.model_name.human(count: 100)}: #{filter.tags&.map(&:name)&.join(", ") || ""}"
      }
    end

    if filter.filtering_by?(:missingtag)
      mt = filter.parameter(:missingtag).presence || "*"
      entries << {
        key: :missingtag,
        icon: "tag",
        type_label: t("application.filters_card.missing_tags"),
        value_html: mt,
        remove_url: url_for(base_params.except(:missingtag)),
        aria_remove: t("application.filters_card.remove_missing_tag_filter"),
        pill_label: "#{t("application.filters_card.missing_tags")}: #{mt}"
      }
    end

    entries
  end

  def tag_cloud_settings
    current_user&.tag_cloud_settings || SiteSettings::UserDefaults::TAG_CLOUD.merge(heatmap: false)
  end

  def renderer_settings
    current_user&.renderer_settings || SiteSettings::UserDefaults::RENDERER
  end

  def file_list_settings
    current_user&.file_list_settings || SiteSettings::UserDefaults::FILE_LIST
  end

  def problem_settings
    current_user&.problem_settings || Problem::DEFAULT_SEVERITIES
  end

  def random_password
    (SecureRandom.base64(32) + "!0aB").chars.shuffle.join
  end

  def server_indicator(object, full_address: false)
    actor = object.respond_to?(:federails_actor) ? object.federails_actor : object
    return if !SiteSettings.federation_enabled? || actor.local?
    link_to sanitize(actor.profile_url), class: "link-primary link-underline-opacity-0 link-underline-opacity-100-hover" do
      safe_join([
        "⁂",
        sanitize(full_address ? actor.at_address : actor.server)
      ], " ")
    end
  end

  def oembed_params
    params.permit(:maxwidth, :maxheight)
  end

  def indexable_select_options(object)
    current = object.inherited_indexable? ? translate("application_helper.indexable_select_options.yes") : translate("application_helper.indexable_select_options.no")
    options_for_select(
      [
        [translate("application_helper.indexable_select_options.inherit", inherited: current), "inherit"],
        [translate("application_helper.indexable_select_options.always_no"), "no"],
        [translate("application_helper.indexable_select_options.always_yes"), "yes"]
      ],
      selected: object&.indexable || "inherit"
    )
  end

  def ai_indexable_select_options(object)
    current = object.inherited_ai_indexable? ? translate("application_helper.indexable_select_options.yes") : translate("application_helper.indexable_select_options.no")
    options_for_select(
      [
        [translate("application_helper.ai_indexable_select_options.inherit", inherited: current), "inherit"],
        [translate("application_helper.ai_indexable_select_options.always_no"), "no"],
        [translate("application_helper.ai_indexable_select_options.always_yes"), "yes"]
      ],
      selected: object&.ai_indexable || "inherit"
    )
  end

  def tour_attributes(id:, title:, description:)
    return {} if current_user.nil? || current_user.first_use?
    tour_state = current_user.tour_state || User::DEFAULT_TOUR_STATE
    {
      "tour-id" => id,
      "tour-id-completed" => (tour_state.dig("completed")&.include?(id) == true).to_s,
      "tour-title" => title,
      "tour-description" => description
    }.compact
  end
end
