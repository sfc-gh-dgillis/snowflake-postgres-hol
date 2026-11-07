-- Connection check: who and where we are on the Postgres instance
SELECT current_user AS pg_user,
       current_database() AS database,
       current_setting('server_version') AS postgres_version,
       inet_server_port() AS port;
