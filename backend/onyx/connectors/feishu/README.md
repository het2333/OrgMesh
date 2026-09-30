# Feishu connector

This connector reads mainland Feishu Drive folders and wiki spaces.
It uses a Feishu internal app and the official `open.feishu.cn` API.

## App setup

1. Create an internal app in the [Feishu developer console](https://open.feishu.cn/app).
2. Enable the read scopes required by the APIs below.
3. Publish the app version with approved scopes.
4. Give the app access to each Drive folder and wiki space.
5. Add the app as a wiki space member.
6. Include indexed users in the app's contact access range.
7. Use App ID and App Secret in the normal connector credential form.

The native credential store encrypts App Secret.
Tenant tokens stay in worker memory and refresh before expiry.

## Admin configuration

Open **Admin → Connectors → Feishu**.
Enter the tenant origin, such as `https://company.feishu.cn`.
Add Drive folder tokens or wiki space IDs.
Folder tokens appear after `/drive/folder/` in folder links.
Use the wiki space ID from Feishu's space settings or spaces API.
The app can read only folders and spaces that grant it access.
At least one folder or wiki space is required.
The normal form sets the poll interval to five minutes.
Poll intervals must remain between 60 and 300 seconds.
Prune intervals must remain between 1 and 300 seconds.
Both intervals default to 300 seconds in native request models.

## API access

Enable scopes shown for each endpoint in the [official API documentation](https://open.feishu.cn/document/home/index).
The app needs content, permission-member, and contact-email read access.
The contact access range must cover document users and owners.

| Purpose | Official API |
| --- | --- |
| Tenant token | `POST /open-apis/auth/v3/tenant_access_token/internal` |
| Folder contents | `GET /open-apis/drive/v1/files` |
| Wiki nodes | `GET /open-apis/wiki/v2/spaces/{space_id}/nodes` |
| New document text | `GET /open-apis/docx/v1/documents/{token}/raw_content` |
| Legacy document text | `GET /open-apis/doc/v2/{token}/raw_content` |
| Sheet metadata | `GET /open-apis/sheets/v3/spreadsheets/{token}/sheets/query` |
| Sheet cells | `GET /open-apis/sheets/v2/spreadsheets/{token}/values/{range}` |
| Table app settings | `GET /open-apis/bitable/v1/apps/{token}` |
| Tables | `GET /open-apis/bitable/v1/apps/{token}/tables` |
| Table records | `GET /open-apis/bitable/v1/apps/{token}/tables/{table_id}/records` |
| Uploaded file | `GET /open-apis/drive/v1/files/{token}/download` |
| Document members | `GET /open-apis/drive/v1/permissions/{token}/members` |
| User email | `GET /open-apis/contact/v3/users/{user_id}` |

## Access rules

Every poll reads the document's current permission-member list.
Direct users map to verified email identities.
User resolution prefers enterprise email, matching directory sync.
Department members map to `feishu:department:<open_department_id>`.
The source never grants public access.
Unknown member types grant no access.
Contact or permission API errors stop retrieval.
Inherited chat, wiki-space, link, and tenant-wide access do not grant access in this version.
The directory sync must use the same department IDs as the permission API.

Advanced Bitable roles can restrict rows and columns.
This version gives these tables no access and reads no rows.
It also denies tables when the advanced-permission state is unavailable.

## Content and deletion checks

The connector reads new documents, legacy documents, sheets, basic tables, and supported uploaded files.
Supported uploads include text, Markdown, CSV, TSV, PDF, DOCX, XLSX, PPTX, and HTML.
Uploaded files have a 50 MiB limit.
Uploaded file parsing stays local and makes no Unstructured API call.
Sheets have a one-million-cell limit.
Requests use connect and read timeouts.
Retries handle temporary failures and rate limits.
Requests never follow redirects or use a tenant-provided API origin.

Source IDs use `feishu:<type>:<token>`.
Original source links and timestamps remain on each document.
Native indexing applies ACL updates before timestamp and content deduplication.
All content is fetched each poll because permission changes can leave content timestamps unchanged.
Native deduplication avoids repeated embedding.
Slim retrieval visits the complete configured scope for native pruning.
It ignores timestamp bounds and stops on incomplete traversal.

## Verification

Run the isolated protocol and connector tests without tenant secrets:

```bash
PYTHONPATH=backend uv run --no-sync pytest -q backend/tests/unit/onyx/connectors/feishu
```

Use real tenant credentials before production deployment.
Check direct users, department users, denied users, revocations, document updates, and source deletions.
