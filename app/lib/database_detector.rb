module DatabaseDetector
  def self.server
    ActiveRecord::Base.with_connection do |connection|
      case connection.adapter_name
      when "PostgreSQL"
        :postgresql
      when "Mysql2"
        :mysql
      when "SQLite"
        :sqlite
      when "NullDB"
        :null
      else
        raise NotImplementedError.new("Unknown database adapter #{connection.adapter_name}")
      end
    end
  end

  def self.is_mysql?
    server == :mysql
  end

  def self.is_mariadb?
    is_mysql?
  end

  def self.is_postgres?
    server == :postgresql
  end

  def self.is_sqlite?
    server == :sqlite
  end

  # Cached per process to avoid repeated DB checks (reduces SQLite lock contention
  # when Rails and Sidekiq share the same DB and caber_ready? is called often).
  @table_ready_cache = {}

  def self.table_ready?(table_name)
    key = table_name.to_s
    return @table_ready_cache[key] if @table_ready_cache.key?(key)

    @table_ready_cache[key] = ActiveRecord::Base.with_connection do |connection|
      connection.data_source_exists? table_name
    end
  end
end
