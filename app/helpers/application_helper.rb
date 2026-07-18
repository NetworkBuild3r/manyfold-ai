module ApplicationHelper
  def dark_theme?
    SiteSettings.validated_theme == "dark"
  end

  # Returns Tailwind class string for settings sidebar nav links. Use for consistent active/inactive styling.
  def settings_nav_link_class(path)
    base = "block px-3 py-2 text-sm rounded-lg no-underline"
    if current_page?(path)
      "#{base} bg-primary-100 text-primary-700 dark:bg-primary-600 dark:text-white font-medium"
    else
      "#{base} text-secondary-700 dark:text-secondary-200 hover:bg-secondary-100 dark:hover:bg-secondary-700"
    end
  end

  # Typography hierarchy: use with h1/h2/h3. Add spacing in view (e.g. mb-4).
  def heading_classes(level = :h1)
    case level
    when :h1, :page
      "font-display text-3xl font-semibold tracking-tight text-secondary-900 dark:text-secondary-100"
    when :h2, :section
      "font-display text-xl font-semibold text-secondary-900 dark:text-secondary-100"
    when :h3, :subsection
      "text-lg font-medium text-secondary-900 dark:text-secondary-100"
    else
      "font-display text-3xl font-semibold tracking-tight text-secondary-900 dark:text-secondary-100"
    end
  end

  # Section divider (replaces raw <hr>). Use: <hr class="<%= divider_classes %>">
  def divider_classes
    "my-6 border-0 border-t border-secondary-200 dark:border-secondary-600"
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
    card_class = ["rounded-xl", "border", "border-secondary-200", "dark:border-secondary-600", "bg-surface", "dark:bg-surface-dark", "shadow-sm", "mb-4", options[:class]].compact.join(" ")
    card_class += " skip-link-container" if options[:skip_link]
    card_data = options[:data] || {}
    card_data = card_data.merge(controller: "collapse") if options[:collapse]
    tag.div class: card_class, data: card_data, id: id do
      safe_join([
        if title.present?
          header_bg = (style.to_s == "primary") ? "bg-primary-600 dark:bg-primary-600" : "bg-secondary-600 dark:bg-secondary-500"
          tag.div(class: "px-4 py-3 text-white rounded-t-xl #{header_bg} relative") do
            if options[:collapse]
              safe_join([
                tag.div(class: "flex items-center justify-between relative z-10") do
                  safe_join([title, tag.span(Icon(icon: "arrows-expand", label: t("general.expand")), class: "md:hidden")])
                end,
                tag.a(
                  nil,
                  class: "md:hidden absolute inset-0 z-0 block",
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
          class: ["p-4", ("collapse-md" if options[:collapse] == "md")].compact.join(" "),
          id: "#{id}-collapse",
          data: (options[:collapse] ? {collapse_target: "content"} : {})
        ) do
          tag.div do
            yield
          end
        end
      ].compact)
    end
  end

  def input_row(form, attribute, type: :text, **options)
    opts = options.dup
    label = opts.delete(:label)
    help = opts.delete(:help)
    case type.to_sym
    when :select
      SelectInputRow(form: form, attribute: attribute, select_options: opts.delete(:select_options), label: label, help: help, options: opts)
    when :collection_select
      CollectionSelectInputRow(form: form, attribute: attribute, collection: opts.delete(:collection), value_method: opts.delete(:value_method), text_method: opts.delete(:text_method), label: label, help: help, options: opts)
    when :numeric
      NumericInputRow(form: form, attribute: attribute, unit: opts.delete(:unit), label: label, help: help, options: opts)
    when :text
      TextInputRow(form: form, attribute: attribute, label: label, help: help, options: opts)
    when :password
      PasswordInputRow(form: form, attribute: attribute, label: label, help: help, options: opts)
    when :url
      UrlInputRow(form: form, attribute: attribute, label: label, help: help, options: opts)
    when :rich_text
      RichTextInputRow(form: form, attribute: attribute, label: label, help: help, options: opts)
    when :checkbox
      CheckBoxInputRow(form: form, attribute: attribute, label: label, help: help, options: opts)
    else
      raise ArgumentError, "Unknown input_row type: #{type}"
    end
  end

  def text_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :text, **options)
  end

  def password_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :password, **options)
  end

  def url_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :url, **options)
  end

  def numeric_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :numeric, **options)
  end

  def rich_text_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :rich_text, **options)
  end

  def checkbox_input_row(form, attribute, options = {})
    input_row(form, attribute, type: :checkbox, **options)
  end

  def select_input_row(form, attribute, select_options, options = {})
    input_row(form, attribute, type: :select, select_options: select_options, **options)
  end

  def collection_select_input_row(form, attribute, collection, value_method, text_method, options = {})
    input_row(form, attribute, type: :collection_select, collection: collection, value_method: value_method, text_method: text_method, **options)
  end

  # Shared Tailwind class strings for submit/action buttons. Matches Components::BaseButton.
  def primary_button_class
    [Components::BaseButton::BASE_CLASSES, Components::BaseButton::VARIANT_CLASSES["primary"]].join(" ")
  end

  def secondary_button_class
    [Components::BaseButton::BASE_CLASSES, Components::BaseButton::VARIANT_CLASSES["secondary"]].join(" ")
  end

  def file_input_row(form, name, options = {})
    input_class = "block w-full rounded-lg border border-secondary-300 px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-800"
    safe_join([
      content_tag(:div) do
        form.label(name, options[:label], class: "block text-sm font-medium text-secondary-700 dark:text-secondary-300")
      end,
      content_tag(:div, class: "mt-1") do
        safe_join [
          content_tag(:div, class: "flex gap-2 items-center") do
            safe_join [
              form.file_field(name, class: input_class),
              options[:remove] ? form.check_box(:"remove_#{name}", class: "rounded border-secondary-300 text-primary-600 focus:ring-primary-500 h-4 w-4", autocomplete: "off") : nil,
              options[:remove] ? form.label(:"remove_#{name}", Icon(icon: "trash", label: options[:remove_label]), class: "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-danger text-danger bg-transparent hover:bg-danger/10 focus-visible:ring-2 focus-visible:ring-primary-500 cursor-pointer") : nil
            ].compact
          end,
          errors_for(form.object, name),
          (options[:help] ? content_tag(:span, class: "text-sm text-secondary-500 dark:text-secondary-400 mt-1 block") { options[:help] } : nil)
        ].compact
      end
    ])
  end

  def nav_link(ico, text, path, options = {})
    link_class = if options[:style].present?
      options[:style]
    else
      active = nav_link_active?(path, options)
      base = "flex items-center gap-1.5 px-3 py-2 rounded-lg no-underline transition-colors focus-visible:ring-2 focus-visible:ring-primary-400 focus-visible:ring-offset-2 focus-visible:ring-offset-secondary-900"
      base += if active
        " text-primary-400 bg-white/10 font-medium"
      else
        " text-secondary-300 hover:text-white hover:bg-white/10"
      end
      base
    end
    aria = {label: options[:aria_label]}
    aria[:current] = "page" if options[:style].blank? && nav_link_active?(path, options)
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

  def nav_link_active?(path, options = {})
    return true if options[:active]
    return false if options[:active] == false
    current_page?(path)
  end

  def errors_for(record, attribute)
    return if record.nil? || attribute.nil?
    return unless record.errors.include? attribute
    content_tag(:div,
      record.errors.full_messages_for(attribute).join("; "),
      class: "text-danger text-sm mt-1 block")
  end

  def skip_link(target, text)
    content_tag :div, class: "skip-link max-w-screen-2xl mx-auto px-4 py-2 bg-primary-600 dark:bg-primary-600 text-white focus-within:ring-2 focus-within:ring-primary-400" do
      link_to text, "##{target}", class: "text-white no-underline focus:underline outline-none"
    end
  end

  def translate_with_locale_wrapper(key, **options)
    translate(key, **options) do |str, _key|
      # Mobility translations expose .locale; plain Strings/Hashes/etc. must pass through.
      if str.respond_to?(:locale) && str.locale
        content_tag(:span, lang: str.locale) { sanitize str }
      else
        str
      end
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
    %i[q collection library creator owner tag missingtag has_image list].filter_map do |key|
      build_active_filter_entry(filter, key, base_params)
    end
  end

  def build_active_filter_entry(filter, key, base_params)
    return unless filter.filtering_by?(key)
    # has_image only shows when enabled (truthy)
    if key == :has_image
      return unless ActiveModel::Type::Boolean.new.cast(filter.parameter(:has_image))
    end
    type_label, value_html, pill_label = active_filter_label_and_value(filter, key)
    return if type_label.nil?
    aria_key = "application.filters_card.remove_#{key}_filter"
    {
      key: key,
      icon: active_filter_icon(key),
      type_label: type_label,
      value_html: value_html,
      remove_url: url_for(base_params.except(key)),
      aria_remove: t(aria_key, default: t("application.filters_card.remove_filter", default: "Remove filter")),
      pill_label: pill_label
    }
  end

  def active_filter_icon(key)
    {q: "search", collection: "collection", library: "boxes", creator: "person", owner: "person", tag: "tag", missingtag: "tag", has_image: "image", list: "heart"}[key]
  end

  def active_filter_label_and_value(filter, key)
    case key
    when :q
      q = filter.parameter(:q)
      [t("application.filters_card.search"), q, "#{t("application.filters_card.search")}: #{q}"]
    when :collection
      coll = filter.collection
      val = coll ? link_to(coll.name, {collection: filter.collection}) : t("application.filters_card.unknown")
      [Collection.model_name.human, val, "#{Collection.model_name.human}: #{coll&.name || t("application.filters_card.unknown")}"]
    when :library
      lib_names = [*filter.parameter(:library)].filter_map { |l| Library.find_by(public_id: l)&.name }
      libs = lib_names.join(", ").presence || t("application.filters_card.unknown")
      [Library.model_name.human, libs, "#{Library.model_name.human}: #{libs}"]
    when :creator
      cr = filter.creator
      val = cr ? link_to(cr.name.careful_titleize, cr) : t("application.filters_card.unknown")
      [Creator.model_name.human, val, "#{Creator.model_name.human}: #{cr&.name&.careful_titleize || t("application.filters_card.unknown")}"]
    when :owner
      u = filter.owner&.username || t("application.filters_card.unknown")
      [t("application.filters_card.owner"), u, "#{t("application.filters_card.owner")}: #{u}"]
    when :tag
      tag_label = ActsAsTaggableOn::Tag.model_name.human(count: 100)
      [tag_label, nil, "#{tag_label}: #{filter.tags&.map(&:name)&.join(", ") || ""}"]
    when :missingtag
      mt = filter.parameter(:missingtag).presence || "*"
      [t("application.filters_card.missing_tags"), mt, "#{t("application.filters_card.missing_tags")}: #{mt}"]
    when :has_image
      label = t("application.filters_card.has_image")
      [label, label, label]
    when :list
      label = t("application.filters_card.list.#{filter.parameter(:list)}", default: filter.parameter(:list).to_s.humanize)
      [t("application.filters_card.list_label"), label, label]
    else
      [nil, nil, nil]
    end
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
    link_to sanitize(actor.profile_url), class: "text-primary-600 dark:text-primary-400 no-underline hover:underline" do
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
