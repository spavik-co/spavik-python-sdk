# Release process

The first public development branch is `dev`. CI tests the code and builds
installable archives; it does not publish to a package registry.

Before the first release:

1. Validate CI from a clean checkout and install the generated archive in a
   separate environment. Confirm package-name ownership on the registry.
2. Prepare a pull request from `dev` to `main`, with the intended version and
   release notes. Keep package metadata and runtime version constants aligned.
3. Configure a dedicated publishing workflow and the registry's trusted
   publisher for this repository. Registry access is not part of the test CI.
4. After merging, tag the reviewed commit on `main` and publish its GitHub
   Release. The future publishing workflow must verify the tag/version match,
   build and test the tagged source, then publish that archive.
5. Install from the registry and run the documented examples against test data.

No publishing workflow is enabled yet. A push or a successful CI run does not
publish a package. Python and TypeScript releases are independent.
