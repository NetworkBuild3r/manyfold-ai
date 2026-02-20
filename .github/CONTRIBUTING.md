# Contributing

We welcome pull requests. By participating in this project, you agree to be respectful and constructive.

**Maintainers:** Keep `main` protected so nothing is merged without passing CI. See [Branch protection for main](docs/branch-protection.md).

Fork, then clone the repo:

    git clone <url-of-this-repository>

Get the app running locally by following the [Running locally](../README.md#running-locally) section in the main README (or use the Devcontainer / Docker instructions there).

Then make sure the tests pass:

    bundle exec rspec
    # or: bundle exec rake

Make your change. Add tests for your change. Make sure the old and new tests both pass!

Push to your fork and open a pull request against this repository.

We try to comment on pull requests within a few days. We may suggest changes, improvements, or alternatives.

Some things that will increase the chance that your pull request is accepted:

* License your contributions under the same license as the project (see [LICENSE.md](../LICENSE.md)).
* Write tests.
* Check that your code passes the project's linters. See the [Standards and testing](../README.md#standards-and-testing) section in the README. For CI commands and how to run checks locally or trigger CI (e.g. for agents), see [CI for agents](docs/ci-for-agents.md).
* Write a [good commit message](https://www.freecodecamp.org/news/how-to-write-better-git-commit-messages/).

AI-assisted or AI-generated contributions are welcome. Please ensure you understand and can vouch for the code you submit, and that it is compatible with the project license.
