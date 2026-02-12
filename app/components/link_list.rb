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
    ul class: "tw:list-none tw:space-y-1 tw:m-0 tw:p-0" do
      @links.each do |link|
        if link.valid?
          li(class: "tw:flex tw:items-center tw:gap-1 tw:flex-wrap") do
            Icon(icon: "link-45deg", role: "presentation") if @icons
            whitespace
            link_to t("sites.%{site}" % {site: link.site}, default: "%{site}" % {site: link.site}), link.url, rel: "noreferrer", class: "tw:no-underline hover:tw:underline"
            if link.deserializer.present? && policy(link.linkable).sync?
              whitespace
              link_to({action: "sync", id: link.linkable, link: link.id}, {method: :post}) do
                Icon(icon: "arrow-repeat", label: t("components.link_list.sync"))
              end
              Icon(icon: "exclamation-triangle-fill", label: "") if link.problems.exists?
            end
          end
        end
      end
    end
  end
end
