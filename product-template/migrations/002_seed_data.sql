-- Seed data: roles, a demo account, and sample users.
-- The admin API key is generated at runtime (see main.py).

INSERT INTO roles (name, description, permissions) VALUES
    ('admin', 'Full access to all resources', 'read,write,admin'),
    ('editor', 'Can read and write resources', 'read,write'),
    ('viewer', 'Read-only access', 'read');

INSERT INTO accounts (name, slug, plan) VALUES
    ('Demo Account', 'demo', 'pro');

INSERT INTO users (account_id, email, name, role_id) VALUES
    (1, 'admin@example.com', 'Admin User', 1),
    (1, 'editor@example.com', 'Editor User', 2),
    (1, 'viewer@example.com', 'Viewer User', 3);

INSERT INTO emails (user_id, address, verified, primary_email) VALUES
    (1, 'admin@example.com', TRUE, TRUE),
    (2, 'editor@example.com', TRUE, TRUE),
    (2, 'editor.alt@example.com', FALSE, FALSE),
    (3, 'viewer@example.com', TRUE, TRUE);
