# Contributing to GentleSeed

Thanks for your interest in GentleSeed! Bug reports, ideas and pull requests are welcome.

## Reporting a bug or suggesting an idea

Open an [issue](https://github.com/KLG-Digital/GentleSeed/issues) with:
- your GentleSeed version and how you run it (Docker or Python);
- what you expected and what happened;
- the relevant lines of the log (hide API keys and addresses you want to keep private).

For a security problem, follow the [security policy](.github/SECURITY.md) instead of opening an issue.

## Working on the code

```bash
pip install -r requirements.txt
python main.py                       # runs GentleSeed locally on port 1853
python scripts/build_frontend.py     # rebuilds web/index.html, web/app.js, web/style.css
```

- Edit the **sources** in `web/pages`, `web/js` and `web/css`, never the generated `web/index.html`, `web/app.js` and `web/style.css`.
- **English is the default language** of every text (interface, server messages, logs). Add the translation of a new text to the 13 files of `web/locales/`: the key is the English text.
- Keep the existing style: banner comments per section and short comments.

## Pull requests

1. Fork the repository and create a branch.
2. Keep each pull request focused on one change.
3. Describe what changes and why.

## License

By contributing, you agree that your contribution is distributed under the [GNU AGPL v3](LICENSE), like the rest of the project.
