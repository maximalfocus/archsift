"""A deterministic, offline PresentationML writer for the executive summary.

FR-017: the executive summary is also delivered as a PPTX deck for stakeholder
presentation. The deck renders exactly the same
:class:`~archsift.executive_summary.ExecutiveSummary` as the executive HTML
report, so the two formats cannot state different facts about one record.

ArchSift writes the OOXML package itself instead of depending on a
presentation library, because the requirements the deck has to meet are
properties of the bytes:

* **Deterministic (NFR-003).** Identical inputs must produce byte-identical
  output on every supported operating system and Python version. Every archive
  member is stored uncompressed with a fixed timestamp, fixed creator system,
  and fixed order, so nothing platform-, clock-, or compression-library-
  dependent can reach the file. A general-purpose presentation library would
  stamp generation times and depend on a compressor's exact output.
* **Offline and self-contained (NFR-001).** Every part is generated here. The
  deck references no external font, image, template, or network location, and
  embeds no media.
* **Injection-safe (NFR-004).** Authored text reaches the package only as
  escaped XML character data inside ``<a:t>``, never as an attribute, a
  relationship target, or a part name.

Masking (NFR-009) is applied when the summary is built, so the deck cannot
carry an unmasked authored value.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Final

from archsift.canonical import JsonObject
from archsift.executive_summary import ExecutiveSummary, build_executive_summary
from archsift.masking import MASKING_POLICY_VERSION, MASKING_WARNING
from archsift.report_text import visible_text

PPTX_REPORT_FORMAT_VERSION: Final = 1

#: The fixed text joining one summary point's values on a slide.
VALUE_SEPARATOR: Final = " — "

#: A deck never truncates: a section longer than this continues on a new slide.
POINTS_PER_SLIDE: Final = 8

# The DOS epoch. ZIP stores local time with no zone, so any real clock reading
# would make output depend on when and where it ran.
_FIXED_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)

#: Owner read/write, declared rather than inherited from the writing host.
_FIXED_EXTERNAL_ATTRIBUTES: Final = 0o600 << 16

# 16:9 at 13.333in x 7.5in, in English Metric Units.
_SLIDE_WIDTH: Final = 12192000
_SLIDE_HEIGHT: Final = 6858000
_MARGIN: Final = 838200
_BODY_WIDTH: Final = _SLIDE_WIDTH - 2 * _MARGIN
_TITLE_TOP: Final = 365125
_TITLE_HEIGHT: Final = 1000125
_BODY_TOP: Final = _TITLE_TOP + _TITLE_HEIGHT + 182563
_BODY_HEIGHT: Final = _SLIDE_HEIGHT - _BODY_TOP - _MARGIN

_XML_DECLARATION: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_A: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P: Final = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT: Final = "http://schemas.openxmlformats.org/package/2006/content-types"
_PR: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
_RT: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CP: Final = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC: Final = "http://purl.org/dc/elements/1.1/"
_EP: Final = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
_PML: Final = "application/vnd.openxmlformats-officedocument.presentationml"


class PptxReportError(ValueError):
    """A summary cannot be written as a deterministic PPTX package."""


def _text(value: str) -> str:
    """Return authored text as escaped XML character data.

    ``visible_text`` runs first so a control character — which XML 1.0 cannot
    represent at all — becomes a visible escape sequence rather than a byte
    that would make the package unreadable.

    The three markup-significant characters are replaced here rather than with
    ``xml.sax.saxutils.escape``, which would pull ``urllib.request`` and
    ``ssl`` into the import graph of a tool that never opens a connection.
    """
    escaped = visible_text(value).replace("&", "&amp;")
    return escaped.replace("<", "&lt;").replace(">", "&gt;")


def _paragraph(text: str, *, size: int, bold: bool, bullet: bool) -> str:
    properties = (
        '<a:pPr marL="285750" indent="-285750"><a:buFont typeface="Arial"/>'
        '<a:buChar char="-"/></a:pPr>'
        if bullet
        else "<a:pPr/>"
    )
    run_properties = f'<a:rPr lang="en-US" sz="{size}" b="{1 if bold else 0}" dirty="0"/>'
    return f"<a:p>{properties}<a:r>{run_properties}<a:t>{_text(text)}</a:t></a:r></a:p>"


def _shape(
    *,
    identifier: int,
    name: str,
    left: int,
    top: int,
    width: int,
    height: int,
    paragraphs: str,
) -> str:
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{identifier}" name="{name}"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{left}" y="{top}"/>'
        f'<a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        '<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr>'
        f"<a:lstStyle/>{paragraphs}</p:txBody>"
        "</p:sp>"
    )


def _slide(title: str, lines: tuple[str, ...]) -> str:
    body = "".join(_paragraph(line, size=1400, bold=False, bullet=True) for line in lines)
    if not body:
        body = '<a:p><a:pPr/><a:endParaRPr lang="en-US"/></a:p>'
    shapes = _shape(
        identifier=2,
        name="Title",
        left=_MARGIN,
        top=_TITLE_TOP,
        width=_BODY_WIDTH,
        height=_TITLE_HEIGHT,
        paragraphs=_paragraph(title, size=2800, bold=True, bullet=False),
    ) + _shape(
        identifier=3,
        name="Body",
        left=_MARGIN,
        top=_BODY_TOP,
        width=_BODY_WIDTH,
        height=_BODY_HEIGHT,
        paragraphs=body,
    )
    return (
        f"{_XML_DECLARATION}"
        f'<p:sld xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{shapes}"
        "</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sld>"
    )


def _theme() -> str:
    colours = (
        ("dk1", '<a:sysClr val="windowText" lastClr="000000"/>'),
        ("lt1", '<a:sysClr val="window" lastClr="FFFFFF"/>'),
        ("dk2", '<a:srgbClr val="1F2933"/>'),
        ("lt2", '<a:srgbClr val="F5F7FA"/>'),
        ("accent1", '<a:srgbClr val="2B6CB0"/>'),
        ("accent2", '<a:srgbClr val="2C7A7B"/>'),
        ("accent3", '<a:srgbClr val="975A16"/>'),
        ("accent4", '<a:srgbClr val="9B2C2C"/>'),
        ("accent5", '<a:srgbClr val="553C9A"/>'),
        ("accent6", '<a:srgbClr val="2F855A"/>'),
        ("hlink", '<a:srgbClr val="2B6CB0"/>'),
        ("folHlink", '<a:srgbClr val="553C9A"/>'),
    )
    scheme = "".join(f"<a:{name}>{value}</a:{name}>" for name, value in colours)
    # Only generic typeface names are declared, so the deck embeds and requests
    # no font file and renders with whatever the reader already has.
    fonts = (
        '<a:fontScheme name="ArchSift">'
        '<a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/>'
        "</a:majorFont>"
        '<a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/>'
        "</a:minorFont>"
        "</a:fontScheme>"
    )
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = (
        '<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr">'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:prstDash val="solid"/></a:ln>'
    )
    effect = "<a:effectStyle><a:effectLst/></a:effectStyle>"
    formats = (
        '<a:fmtScheme name="ArchSift">'
        f"<a:fillStyleLst>{fill * 3}</a:fillStyleLst>"
        f"<a:lnStyleLst>{line * 3}</a:lnStyleLst>"
        f"<a:effectStyleLst>{effect * 3}</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst>"
        "</a:fmtScheme>"
    )
    return (
        f"{_XML_DECLARATION}"
        f'<a:theme xmlns:a="{_A}" name="ArchSift">'
        f'<a:themeElements><a:clrScheme name="ArchSift">{scheme}</a:clrScheme>'
        f"{fonts}{formats}</a:themeElements>"
        "<a:objectDefaults/><a:extraClrSchemeLst/>"
        "</a:theme>"
    )


_EMPTY_SP_TREE: Final = (
    "<p:cSld><p:spTree>"
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
    "</p:spTree></p:cSld>"
)
_CLR_MAP: Final = (
    '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2"'
    ' accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink"'
    ' folHlink="folHlink"/>'
)


def _slide_master() -> str:
    return (
        f"{_XML_DECLARATION}"
        f'<p:sldMaster xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        f"{_EMPTY_SP_TREE}{_CLR_MAP}"
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )


def _slide_layout() -> str:
    return (
        f"{_XML_DECLARATION}"
        f'<p:sldLayout xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}" type="blank"'
        ' preserve="1">'
        f"{_EMPTY_SP_TREE}"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sldLayout>"
    )


def _presentation(slide_count: int) -> str:
    slides = "".join(
        f'<p:sldId id="{256 + index}" r:id="rId{index + 2}"/>' for index in range(slide_count)
    )
    return (
        f"{_XML_DECLARATION}"
        f'<p:presentation xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{slides}</p:sldIdLst>"
        f'<p:sldSz cx="{_SLIDE_WIDTH}" cy="{_SLIDE_HEIGHT}"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )


def _relationships(entries: tuple[tuple[str, str, str], ...]) -> str:
    items = "".join(
        f'<Relationship Id="{identifier}" Type="{kind}" Target="{target}"/>'
        for identifier, kind, target in entries
    )
    return f'{_XML_DECLARATION}<Relationships xmlns="{_PR}">{items}</Relationships>'


def _content_types(slide_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index + 1}.xml" ContentType="{_PML}.slide+xml"/>'
        for index in range(slide_count)
    )
    return (
        f"{_XML_DECLARATION}"
        f'<Types xmlns="{_CT}">'
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/ppt/presentation.xml" ContentType="{_PML}.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml"'
        f' ContentType="{_PML}.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml"'
        f' ContentType="{_PML}.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f"{overrides}"
        '<Override PartName="/docProps/core.xml"'
        ' ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def _core_properties(summary: ExecutiveSummary) -> str:
    # No created or modified date is written: a timestamp would be exactly the
    # run-variant metadata NFR-003 forbids.
    return (
        f"{_XML_DECLARATION}"
        f'<cp:coreProperties xmlns:cp="{_CP}" xmlns:dc="{_DC}">'
        f"<dc:title>{_text('ArchSift Executive Summary')}</dc:title>"
        f"<dc:subject>{_text(summary.case_title)}</dc:subject>"
        f"<dc:identifier>{_text(summary.record_content_identity)}</dc:identifier>"
        "<cp:revision>1</cp:revision>"
        "</cp:coreProperties>"
    )


def _app_properties(slide_count: int) -> str:
    return (
        f"{_XML_DECLARATION}"
        f'<Properties xmlns="{_EP}">'
        "<Application>ArchSift</Application>"
        f"<Slides>{slide_count}</Slides>"
        "<ScaleCrop>false</ScaleCrop>"
        "<LinksUpToDate>false</LinksUpToDate>"
        "<SharedDoc>false</SharedDoc>"
        "<HyperlinksChanged>false</HyperlinksChanged>"
        "</Properties>"
    )


def _rendered_lines(summary: ExecutiveSummary) -> list[tuple[str, tuple[str, ...]]]:
    """Return every slide's title and bullet lines, paginating without truncating."""
    slides: list[tuple[str, tuple[str, ...]]] = [
        (
            "ArchSift Executive Summary",
            (
                summary.case_title,
                f"Record: {summary.record_content_identity}",
                f"Ruleset: {summary.ruleset_version}",
                f"ArchSift: {summary.tool_version}",
            ),
        )
    ]
    for section in summary.sections:
        lines = [f"{point.label}: {VALUE_SEPARATOR.join(point.values)}" for point in section.points]
        for start in range(0, max(len(lines), 1), POINTS_PER_SLIDE):
            page = lines[start : start + POINTS_PER_SLIDE]
            title = section.title if start == 0 else f"{section.title} (continued)"
            slides.append((title, tuple(page)))
    slides.append(
        (
            "Masking Notice",
            (f"Policy version: {MASKING_POLICY_VERSION}", MASKING_WARNING),
        )
    )
    return slides


def _package(parts: tuple[tuple[str, str], ...]) -> bytes:
    """Return one ZIP package whose bytes depend only on the part contents."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in parts:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
            # Every field zipfile would otherwise derive from the host is
            # pinned, so the same parts produce the same bytes everywhere.
            info.compress_type = zipfile.ZIP_STORED
            # `create_system` is the field that would otherwise say whether the
            # deck was written on Windows or on a POSIX host.
            info.create_system = 0
            info.create_version = 20
            info.extract_version = 20
            # zipfile substitutes `0o600 << 16` for an unset attribute, so the
            # same permissions are declared here rather than left to it.
            info.external_attr = _FIXED_EXTERNAL_ATTRIBUTES
            info.internal_attr = 0
            info.flag_bits = 0
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


def render_executive_summary_pptx(summary: ExecutiveSummary) -> bytes:
    """Return one deterministic offline PPTX deck for an executive summary."""
    slides = _rendered_lines(summary)
    if not slides:  # pragma: no cover - the title slide is unconditional
        raise PptxReportError("An executive summary deck must contain at least one slide.")
    parts: list[tuple[str, str]] = [
        ("[Content_Types].xml", _content_types(len(slides))),
        (
            "_rels/.rels",
            _relationships(
                (
                    ("rId1", f"{_RT}/officeDocument", "ppt/presentation.xml"),
                    (
                        "rId2",
                        "http://schemas.openxmlformats.org/package/2006/"
                        "relationships/metadata/core-properties",
                        "docProps/core.xml",
                    ),
                    ("rId3", f"{_RT}/extended-properties", "docProps/app.xml"),
                )
            ),
        ),
        ("docProps/app.xml", _app_properties(len(slides))),
        ("ppt/presentation.xml", _presentation(len(slides))),
        (
            "ppt/_rels/presentation.xml.rels",
            _relationships(
                (
                    ("rId1", f"{_RT}/slideMaster", "slideMasters/slideMaster1.xml"),
                    *(
                        (f"rId{index + 2}", f"{_RT}/slide", f"slides/slide{index + 1}.xml")
                        for index in range(len(slides))
                    ),
                    (f"rId{len(slides) + 2}", f"{_RT}/theme", "theme/theme1.xml"),
                )
            ),
        ),
        ("ppt/slideMasters/slideMaster1.xml", _slide_master()),
        (
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _relationships(
                (
                    ("rId1", f"{_RT}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                    ("rId2", f"{_RT}/theme", "../theme/theme1.xml"),
                )
            ),
        ),
        ("ppt/slideLayouts/slideLayout1.xml", _slide_layout()),
        (
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            _relationships((("rId1", f"{_RT}/slideMaster", "../slideMasters/slideMaster1.xml"),)),
        ),
        ("ppt/theme/theme1.xml", _theme()),
    ]
    for index, (title, lines) in enumerate(slides, start=1):
        parts.append((f"ppt/slides/slide{index}.xml", _slide(title, lines)))
        parts.append(
            (
                f"ppt/slides/_rels/slide{index}.xml.rels",
                _relationships(
                    (("rId1", f"{_RT}/slideLayout", "../slideLayouts/slideLayout1.xml"),)
                ),
            )
        )
    # docProps/core.xml is written last so the package order stays fixed
    # regardless of how many slides the summary needs.
    parts.append(("docProps/core.xml", _core_properties(summary)))
    return _package(tuple(parts))


def render_executive_pptx_report(record: JsonObject) -> bytes:
    """Return one deterministic executive PPTX deck for a loaded canonical record."""
    return render_executive_summary_pptx(build_executive_summary(record))
