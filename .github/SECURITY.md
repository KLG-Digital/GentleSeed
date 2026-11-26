# Security Policy

## Supported versions

Only the latest release receives security fixes. Please update before reporting an issue.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: go to the **Security** tab of the [GentleSeed repository](https://github.com/KLG-Digital/GentleSeed/security) and choose **Report a vulnerability**.

Include, if you can:
- the GentleSeed version and how you run it (Docker or Python);
- the steps to reproduce the problem;
- what an attacker could do with it.

Never include your real API keys, passwords or the contents of your `data/` folder.

You will get an answer as soon as possible. Once a fix is released, the issue can be disclosed publicly.

## Good practices when running GentleSeed

- Keep **form sign-in** enabled and use a strong password.
- Do not expose the port directly on the Internet; use a VPN or an HTTPS reverse proxy.
- Keep `/data` (or `data/`) private: it holds your settings and API keys.
