# DDC Automation Landing Page

This repository hosts the static landing page that powers the project site at
[howtocuddle.github.io/ddc-automation](https://howtocuddle.github.io/ddc-automation/).

## Local development

You can preview the page locally using any static file server. The example below
uses Python, but feel free to substitute your preferred tool.

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000> in your browser to view the page.

## Deployment

GitHub Pages automatically serves the contents of the default branch. Once your
changes are merged, push to GitHub and the site will update in a few minutes.

## Reference tables

The repository now exposes the cleaned Dewey Decimal auxiliary tables alongside
the main landing page:

* `tables/index.html` provides an on-demand viewer that renders each table in an
  accessible HTML layout.
* `tables/data/table1.json` through `tables/data/table6.json` deliver the raw
  JSON files for Tables 1–6.

Serve the project locally (as shown above) to browse both `index.html` and the
`tables/` directory exactly as they will appear on GitHub Pages.
