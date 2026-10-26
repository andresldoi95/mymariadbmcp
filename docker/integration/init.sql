CREATE DATABASE IF NOT EXISTS mcp_test;

CREATE TABLE mcp_test.sample_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    label VARCHAR(128) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO mcp_test.sample_records (label)
VALUES ('first'), ('second'), ('third');

CREATE TABLE mcp_test.private_records (
    id INT NOT NULL PRIMARY KEY,
    secret VARCHAR(64) NOT NULL
);

INSERT INTO mcp_test.private_records VALUES (1, 'not-for-the-runtime-account');

CREATE USER 'mcp_ro'@'%' IDENTIFIED BY 'disposable-test-password' REQUIRE SSL;
GRANT SELECT ON mcp_test.* TO 'mcp_ro'@'%';

CREATE ROLE 'mcp_write_role';
GRANT SELECT, INSERT ON mcp_test.* TO 'mcp_write_role';
CREATE USER 'mcp_privileged'@'%' IDENTIFIED BY 'disposable-test-password' REQUIRE SSL;
GRANT 'mcp_write_role' TO 'mcp_privileged'@'%';
SET DEFAULT ROLE 'mcp_write_role' FOR 'mcp_privileged'@'%';
