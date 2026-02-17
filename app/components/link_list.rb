# frozen_string_literal: true

class Components::LinkList < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  register_value_helper :policy

  def initialize(links:, icons: true)
    @links = links
    @icons = icons
  end

  def view_template
    return if @links.empty?
    ul class: "list-none space-y-1 m-0 p-0" do
      @links.each do |link|
        if link.valid?
          li(class: "flex items-center gap-1 flex-wrap") do
            span(class: "text-secondary-700 dark:text-secondary-300") { Icon(icon: "link-45deg", role: "presentation") } if @icons
            whitespace
            link_to t("sites.%{site}" % {site: link.site}, default: "%{site}" % {site: link.site}), link.url, rel: "noreferrer", class: "no-underline hover:underline"
            if link.deserializer.present? && policy(link.linkable).sync?
              whitespace
              link_to({action: "sync", id: link.linkable, link: link.id}, {method: :post}, class: "text-secondary-700 dark:text-secondary-300") do
                Icon(icon: "arrow-repeat", label: t("components.link_list.sync"))
              end
              span(class: "text-secondary-700 dark:text-secondary-300") { Icon(icon: "exclamation-triangle-fill", label: "") } if link.problems.exists?
            end
          end
        end
      end
    end
  end
end
