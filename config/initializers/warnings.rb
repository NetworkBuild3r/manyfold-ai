# Only run when sqlite3 is in use (e.g. CI matrix with sqlite); avoid NameError when using postgres/mysql.
SQLite3::ForkSafety.suppress_warnings! if defined?(SQLite3)
