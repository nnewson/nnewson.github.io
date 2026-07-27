# fireEngine Devlog

The source for [nnewson.github.io](https://nnewson.github.io), a Jekyll blog
using the [Chirpy](https://github.com/cotes2020/jekyll-theme-chirpy) theme.

The blog follows the development of
[fireEngine](https://github.com/nnewson/fireEngine-tutorial). Each engine
release can have a matching post explaining what changed, why it changed, and
what comes next.

## Publish with GitHub Pages

The workflow in `.github/workflows/pages-deploy.yml` builds and deploys the
site whenever a change is pushed to `main`.

One repository setting must be enabled on GitHub:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Push this repository to `main` and follow the **Build and Deploy** workflow
   in the Actions tab.

Once that workflow succeeds, the site is available at
<https://nnewson.github.io>.

Pull requests run a separate build and link check without deploying.

## Write a release post

Copy `_drafts/release-template.md` to a dated filename under `_posts`:

```text
_posts/YYYY-MM-DD-fireengine-vX-Y-Z.md
```

Update the front matter and replace the prompts in the body. Use the engine
release/tag URL for `release_url` so readers can move between the explanation
and its exact source snapshot.

Chirpy's full post syntax is documented in
[Writing a New Post](https://chirpy.cotes.page/posts/write-a-new-post/).

## Run locally

The deployment uses Ruby 3.4. With a compatible Ruby and Bundler installed:

```shell
bundle install
bundle exec jekyll serve
```

Then open <http://127.0.0.1:4000>.

Docker can be used instead of installing Ruby locally:

```shell
docker run --rm -it -p 4000:4000 \
  -v "$PWD":/site -w /site ruby:3.4 \
  bash -lc "bundle install && bundle exec jekyll serve --host 0.0.0.0"
```

## Site configuration

The main metadata and feature settings live in `_config.yml`. Restart the local
Jekyll server after changing that file.
