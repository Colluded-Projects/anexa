from __future__ import annotations

import json
import time
from typing import Any

import jwt

from ..graph.ontology import TEXT_PROP, entity_key, person_key
from . import register
from ._http import as_bool, as_int, json_body, send
from .base import (
    Connector,
    ConnectorContext,
    ConnectorError,
    ConnectorSpec,
    EdgeUpsert,
    FieldSpec,
    GraphDelta,
    NodeUpsert,
    OperationResult,
    OperationSpec,
)

DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/documents"
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
DOC_MIME = "application/vnd.google-apps.document"
FILE_FIELDS = (
    "nextPageToken, files(id, name, mimeType, webViewLink, createdTime, modifiedTime, "
    "owners(displayName, emailAddress, permissionId))"
)
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_TEXT = 4000
_TOKEN_CACHE = "google_access_token"


def document_text(document: dict[str, Any]) -> str:
    """Plain text of a Docs API document, including text inside tables."""

    def walk(elements: list[dict[str, Any]]) -> str:
        out = []
        for element in elements or []:
            if "paragraph" in element:
                for part in element["paragraph"].get("elements", []):
                    out.append((part.get("textRun") or {}).get("content", ""))
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        out.append(walk(cell.get("content", [])))
            elif "tableOfContents" in element:
                out.append(walk(element["tableOfContents"].get("content", [])))
        return "".join(out)

    return walk((document.get("body") or {}).get("content", []))


class GoogleConnector(Connector):
    spec = ConnectorSpec(
        key="google",
        title="Google Workspace",
        description="Read and write Google Docs, and map Drive documents to their owners.",
        config_fields=[
            FieldSpec(
                name="service_account_json",
                label="Service account key (JSON)",
                type="text",
                secret=True,
                help="Paste the key file of a service account that the documents are shared "
                "with, or that has domain-wide delegation.",
            ),
            FieldSpec(
                name="access_token",
                label="Access token",
                secret=True,
                help="Alternative to a service account: a short-lived OAuth access token with "
                "Drive and Docs scopes.",
            ),
            FieldSpec(
                name="subject",
                label="Act as user",
                placeholder="someone@your-company.com",
                help="With domain-wide delegation, the user the service account impersonates.",
            ),
        ],
        operations=[
            OperationSpec(
                name="list_files",
                title="List files",
                description="List Drive files, optionally filtered with a Drive search query.",
                params=[
                    FieldSpec(name="query", label="Drive query",
                              placeholder="name contains 'roadmap' and trashed = false"),
                    FieldSpec(name="limit", label="Limit", type="number", default=50),
                ],
            ),
            OperationSpec(
                name="get_document",
                title="Get document",
                description="Read a Google Doc as plain text.",
                params=[FieldSpec(name="document_id", label="Document ID", required=True)],
            ),
            OperationSpec(
                name="create_document",
                title="Create document",
                params=[
                    FieldSpec(name="title", label="Title", required=True),
                    FieldSpec(name="text", label="Text", type="text"),
                ],
            ),
            OperationSpec(
                name="append_text",
                title="Append text",
                description="Add text to the end of a Google Doc.",
                params=[
                    FieldSpec(name="document_id", label="Document ID", required=True),
                    FieldSpec(name="text", label="Text", type="text", required=True),
                ],
            ),
            OperationSpec(
                name="sync_docs",
                title="Sync documents",
                kind="sync",
                description="Add Google Docs as Documents, linked to the people who own them.",
                params=[
                    FieldSpec(name="query", label="Drive query",
                              help="Defaults to every Google Doc that is not in the bin."),
                    FieldSpec(name="limit", label="Limit", type="number", default=200),
                    FieldSpec(
                        name="include_content",
                        label="Include content",
                        type="boolean",
                        default=True,
                        help="Export each Google Doc as plain text (one request per doc).",
                    ),
                ],
            ),
        ],
    )

    # --- auth ----------------------------------------------------------------
    def _service_account_token(self, ctx: ConnectorContext, raw: Any) -> str:
        try:
            info = raw if isinstance(raw, dict) else json.loads(raw)
            email, private_key = info["client_email"], info["private_key"]
        except (ValueError, TypeError, KeyError) as exc:
            raise ConnectorError(
                "google: service account key must be the JSON key file with client_email and "
                "private_key"
            ) from exc
        token_uri = info.get("token_uri") or DEFAULT_TOKEN_URI
        now = int(time.time())
        claims = {"iss": email, "scope": SCOPES, "aud": token_uri, "iat": now, "exp": now + 3600}
        if ctx.config.get("subject"):
            claims["sub"] = ctx.config["subject"]
        headers = {"kid": info["private_key_id"]} if info.get("private_key_id") else None
        try:
            assertion = jwt.encode(claims, private_key, algorithm="RS256", headers=headers)
        except Exception as exc:  # malformed PEM surfaces as several unrelated types
            raise ConnectorError("google: service account private key is not usable") from exc
        resp = send(
            ctx, "google", "POST", token_uri, data={"grant_type": JWT_GRANT, "assertion": assertion}
        )
        token = json_body(resp, "google").get("access_token")
        if not token:
            raise ConnectorError("google: token endpoint returned no access_token")
        return token

    def _token(self, ctx: ConnectorContext) -> str:
        if _TOKEN_CACHE not in ctx.extras:
            if ctx.secrets.get("service_account_json"):
                token = self._service_account_token(ctx, ctx.secrets["service_account_json"])
            elif ctx.secrets.get("access_token"):
                token = str(ctx.secrets["access_token"]).strip()
            else:
                raise ConnectorError(
                    "google: connection needs a service account key or an access token"
                )
            ctx.extras[_TOKEN_CACHE] = token
        return ctx.extras[_TOKEN_CACHE]

    def _request(self, ctx: ConnectorContext, method: str, url: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self._token(ctx)}"}
        return json_body(send(ctx, "google", method, url, headers=headers, **kwargs), "google")

    # --- helpers -------------------------------------------------------------
    def _files(self, ctx: ConnectorContext, query: str | None, limit: int) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "fields": FILE_FIELDS,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if query:
            params["q"] = query
        for _ in range(MAX_PAGES):
            params["pageSize"] = min(PAGE_SIZE, limit - len(files))
            body = self._request(ctx, "GET", f"{DRIVE}/files", params=params)
            files.extend(body.get("files") or [])
            token = body.get("nextPageToken")
            if not token or len(files) >= limit:
                break
            params = {**params, "pageToken": token}
        return files[:limit]

    @staticmethod
    def _file(file: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": file.get("id"),
            "name": file.get("name"),
            "mime_type": file.get("mimeType"),
            "url": file.get("webViewLink"),
            "created_at": file.get("createdTime"),
            "modified_at": file.get("modifiedTime"),
            "owners": [o.get("emailAddress") for o in file.get("owners") or []],
        }

    def _append(self, ctx: ConnectorContext, document_id: str, text: str) -> None:
        requests = [{"insertText": {"endOfSegmentLocation": {}, "text": text}}]
        self._request(
            ctx, "POST", f"{DOCS}/documents/{document_id}:batchUpdate", json={"requests": requests}
        )

    def _export_text(self, ctx: ConnectorContext, file_id: str) -> str:
        headers = {"Authorization": f"Bearer {self._token(ctx)}"}
        resp = send(
            ctx, "google", "GET", f"{DRIVE}/files/{file_id}/export",
            headers=headers, params={"mimeType": "text/plain"},
        )
        return resp.text

    @staticmethod
    def _doc_url(document_id: str) -> str:
        return f"https://docs.google.com/document/d/{document_id}/edit"

    # --- operations ----------------------------------------------------------
    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.validate_params(operation, params)
        return getattr(self, f"_op_{operation}")(params, ctx)

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        about = self._request(
            ctx, "GET", f"{DRIVE}/about", params={"fields": "user(displayName, emailAddress)"}
        )
        user = about.get("user") or {}
        return {"name": user.get("displayName"), "email": user.get("emailAddress")}

    def _op_list_files(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        limit = as_int(params.get("limit"), 50, 1, PAGE_SIZE * MAX_PAGES)
        files = [self._file(f) for f in self._files(ctx, params.get("query") or None, limit)]
        return OperationResult(output={"files": files, "count": len(files)})

    def _op_get_document(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        document_id = params["document_id"]
        document = self._request(ctx, "GET", f"{DOCS}/documents/{document_id}")
        return OperationResult(
            output={
                "document_id": document.get("documentId", document_id),
                "title": document.get("title"),
                "text": document_text(document),
                "url": self._doc_url(document_id),
            }
        )

    def _op_create_document(
        self, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        document = self._request(ctx, "POST", f"{DOCS}/documents", json={"title": params["title"]})
        document_id = document.get("documentId")
        if not document_id:
            raise ConnectorError("google: create document returned no documentId")
        if params.get("text"):
            self._append(ctx, document_id, str(params["text"]))
        return OperationResult(
            output={
                "document_id": document_id,
                "title": document.get("title", params["title"]),
                "url": self._doc_url(document_id),
            }
        )

    def _op_append_text(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        document_id, text = params["document_id"], str(params["text"])
        self._append(ctx, document_id, text)
        return OperationResult(
            output={
                "document_id": document_id,
                "appended_chars": len(text),
                "url": self._doc_url(document_id),
            }
        )

    def _op_sync_docs(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        limit = as_int(params.get("limit"), 200, 1, PAGE_SIZE * MAX_PAGES)
        query = params.get("query") or f"mimeType = '{DOC_MIME}' and trashed = false"
        include_content = as_bool(params.get("include_content"), True)
        delta = GraphDelta()
        people: dict[str, NodeUpsert] = {}
        files = self._files(ctx, query, limit)
        for file in files:
            info = self._file(file)
            doc_key = entity_key("google", "file", info["id"])
            props = {
                "name": info["name"],
                "url": info["url"],
                "mime_type": info["mime_type"],
                "google_id": info["id"],
                "created_at": info["created_at"],
                "modified_at": info["modified_at"],
            }
            if include_content and info["mime_type"] == DOC_MIME:
                props[TEXT_PROP] = self._export_text(ctx, info["id"])[:MAX_TEXT]
            delta.nodes.append(NodeUpsert(label="Document", key=doc_key, props=props))
            for owner in file.get("owners") or []:
                email = owner.get("emailAddress")
                external_id = owner.get("permissionId") or email
                if not external_id:
                    continue
                person = people.setdefault(
                    external_id,
                    NodeUpsert(
                        label="Person",
                        key=person_key(email, "google", external_id),
                        props={"name": owner.get("displayName") or email, "email": email},
                    ),
                )
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Person",
                        src_key=person.key,
                        type="OWNS",
                        dst_label="Document",
                        dst_key=doc_key,
                    )
                )
        delta.nodes.extend(people.values())
        return OperationResult(
            output={"documents": len(files), "people": len(people)}, graph=delta
        )


register(GoogleConnector())
