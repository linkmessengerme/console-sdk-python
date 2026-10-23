# Releasing

Use `Link Messenger <dev@linkmessenger.me>` for Git authors, committers and
taggers. Publish through the Link Messenger account or GitHub Actions. Review
source, history and built archives for personal names, paths and credentials.

1. Update both the package version and the runtime version; date the changelog.
2. Run the release checks:

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m build
python -m twine check dist/*
```

3. Install the built package in a clean consumer environment and verify its API.
4. Commit the reviewed changes on a release branch and publish them to `main`.
   The release workflow reruns checks, creates an annotated version tag and a
   GitHub release. Existing tags are never moved.
5. Upload the reviewed wheel and sdist with `python -m twine upload dist/*`.
   Use the Link Messenger PyPI account's project-scoped token, supplied through
   `TWINE_USERNAME=__token__` and `TWINE_PASSWORD` in the publishing process.
   Do not put credentials in source, shell history or repository files.
6. Verify both registry files and install the release from PyPI in a clean venv.

The workflow retains the built distributions as an artifact. PyPI upload is
separate until a matching Trusted Publisher is configured on PyPI; the previous
OIDC upload failed with `invalid-publisher`. Never overwrite an existing version.
