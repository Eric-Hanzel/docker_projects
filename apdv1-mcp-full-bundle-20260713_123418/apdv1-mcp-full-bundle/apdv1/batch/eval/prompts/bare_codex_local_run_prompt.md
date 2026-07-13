# Local Deployment Task

The runner will provide one JSON object containing `url` and any necessary extras such as `license_key`.

Please use the provided target to set up the project locally on this machine. Use the official installation or self-hosting documentation where available, prefer the simplest reasonable Docker or Docker Compose path when it fits, and verify that the running project is actually usable from the host.

Do not treat container health, an open port, a health endpoint, or a generic HTTP 200 page as sufficient by itself. Complete the normal first-run/business initialization when the project requires it, such as creating the first admin/user, applying a license key, running migrations, creating a project/bucket/repository/dashboard, or logging in. Verify at least one meaningful baseline function through the intended UI/API boundary and report the concrete action and result.

When you finish, tell me the local URL, any credentials or provided extras you used, what you verified, and anything that is still blocked.
