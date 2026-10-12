# Runtime image notices

The Dockerfile is a review template. No image was built or pulled during this task.
Resolve and record official image digests before an approved image build.

The Go binary includes the notices in `THIRD_PARTY_NOTICES.txt`.
The file contains full local license texts for Go and all six pinned runtime modules.
Go, x/sync, and x/text use BSD-style licenses. The jackc modules use MIT licenses.
The root repository license also remains in the runtime image.

The runtime template uses Debian Bookworm, curl, and ca-certificates.
Keep `/usr/share/doc/*/copyright`, including transitive dependency notices.
The Dockerfile checks the curl and ca-certificates notice files during image build.
It records exact installed package versions in `runtime-packages.txt`.
Do not strip the copyright files when reducing the image.

Before distribution, inspect the actual built image's package inventory and notices.
Check curl, its TLS library, libc, certificate packages, and every installed dependency.
Export the inventory and full notices with the distributed image.
Check the base image's source and license obligations for the resolved digest.
The template and local Go license checks do not prove a future runtime image compliant.
