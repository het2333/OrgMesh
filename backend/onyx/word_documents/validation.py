"""Bounded, non-executing OPC validation. Original DOCX bytes stay authoritative."""

import posixpath
import stat
import zlib
from io import BytesIO
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

MAX_DOCX_BYTES = 20 * 1024 * 1024
MAX_INFLATED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAIN_TYPE = DOCX_MIME + ".main+xml"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)


def _invalid() -> OnyxError:
    return OnyxError(OnyxErrorCode.INVALID_INPUT, "Unsupported or unsafe DOCX package")


def _xml(data: bytes) -> ET.Element:
    return fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def _safe_name(name: str) -> bool:
    return (
        bool(name)
        and "\\" not in name
        and "\x00" not in name
        and ":" not in name
        and unquote(name) == name
        and not name.startswith("/")
        and all(part not in ("", ".", "..") for part in name.rstrip("/").split("/"))
    )


def _validate_relationships(root: ET.Element, name: str, names: set[str]) -> None:
    if root.tag != f"{{{REL_NS}}}Relationships":
        raise _invalid()
    base = "" if name == "_rels/.rels" else posixpath.dirname(posixpath.dirname(name))
    for relation in root:
        target = relation.get("Target", "")
        kind = relation.get("Type", "").lower()
        uri = urlsplit(target)
        if (
            relation.tag != f"{{{REL_NS}}}Relationship"
            or relation.get("TargetMode", "Internal") != "Internal"
            or not target
            or uri.scheme
            or uri.netloc
            or uri.query
            or "\\" in target
            or unquote(target) != target
            or any(
                term in kind
                for term in (
                    "afchunk",
                    "vbaproject",
                    "oleobject",
                    "activex",
                )
            )
        ):
            raise _invalid()
        resolved = (
            posixpath.normpath(posixpath.join(base, uri.path))
            if not uri.path.startswith("/")
            else uri.path[1:]
        )
        if not _safe_name(resolved) or resolved not in names:
            raise _invalid()


def _xml_parts(types: ET.Element, names: set[str]) -> set[str]:
    if types.tag != f"{{{TYPE_NS}}}Types":
        raise _invalid()
    xml_parts = {
        name
        for name in names
        if name.lower().endswith((".xml", ".rels", ".vml", ".svg"))
    }
    found_main = False
    for entry in types:
        kind = entry.get("ContentType", "").lower()
        if any(
            term in kind
            for term in ("macroenabled", "vbaproject", "activex", "oleobject")
        ):
            raise _invalid()
        if entry.get("PartName") == "/word/document.xml" and kind == MAIN_TYPE:
            found_main = True
        if kind.endswith(("xml", "vmldrawing")):
            if entry.tag == f"{{{TYPE_NS}}}Override":
                part_name = entry.get("PartName", "").removeprefix("/")
                if part_name not in names:
                    raise _invalid()
                xml_parts.add(part_name)
            elif entry.tag == f"{{{TYPE_NS}}}Default":
                extension = entry.get("Extension", "").lower()
                xml_parts.update(
                    name for name in names if name.lower().endswith("." + extension)
                )
    if not found_main:
        raise _invalid()
    return xml_parts


def validate_docx(content: bytes) -> None:
    if len(content) > MAX_DOCX_BYTES:
        raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE, "DOCX exceeds 20 MiB")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_ZIP_ENTRIES
                or sum(item.file_size for item in entries) > MAX_INFLATED_BYTES
            ):
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    "DOCX package exceeds extraction limits",
                )
            names = {item.filename for item in entries}
            if len(names) != len(entries) or not {
                "[Content_Types].xml",
                "_rels/.rels",
                "word/document.xml",
            }.issubset(names):
                raise _invalid()
            with archive.open("[Content_Types].xml") as type_file:
                types = _xml(type_file.read(MAX_INFLATED_BYTES + 1))
            xml_parts = _xml_parts(types, names)
            roots: dict[str, ET.Element] = {}
            actual_size = 0
            for item in entries:
                name = item.filename
                lowered = name.lower()
                if (
                    not _safe_name(name)
                    or item.flag_bits & 1
                    or item.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or "vbaproject" in lowered
                    or "/activex/" in lowered
                    or "/embeddings/" in lowered
                ):
                    raise _invalid()
                if item.is_dir():
                    continue
                with archive.open(item) as part:
                    data = part.read(MAX_INFLATED_BYTES - actual_size + 1)
                actual_size += len(data)
                if actual_size > MAX_INFLATED_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        "DOCX package exceeds extraction limits",
                    )
                if len(data) != item.file_size:
                    raise _invalid()
                if name in xml_parts:
                    root = _xml(data)
                    if name in ("word/document.xml", "_rels/.rels"):
                        roots[name] = root
                    for element in root.iter():
                        if element.tag.rsplit("}", 1)[-1].lower() in (
                            "altchunk",
                            "object",
                            "oleobject",
                        ):
                            raise _invalid()
                    if lowered.endswith(".rels"):
                        _validate_relationships(root, name, names)
            if roots["word/document.xml"].tag != f"{{{WORD_NS}}}document":
                raise _invalid()
            if not any(
                rel.get("Type") == OFFICE_REL
                and rel.get("Target") in ("word/document.xml", "/word/document.xml")
                for rel in roots["_rels/.rels"]
            ):
                raise _invalid()
    except (
        BadZipFile,
        zlib.error,
        DefusedXmlException,
        ET.ParseError,
        ValueError,
        OSError,
        RuntimeError,
        NotImplementedError,
        KeyError,
    ) as exc:
        raise _invalid() from exc


def blank_docx() -> bytes:
    parts = {
        "[Content_Types].xml": f'<Types xmlns="{TYPE_NS}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="{MAIN_TYPE}"/></Types>',
        "_rels/.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Type="{OFFICE_REL}" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<w:document xmlns:w="{WORD_NS}"><w:body><w:p/><w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>',
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, xml in parts.items():
            # Fixed timestamps make retries of a new blank document identical.
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(
                info, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml
            )
    return output.getvalue()
