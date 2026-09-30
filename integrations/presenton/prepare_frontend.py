"""Prepare the pinned Presenton editor for the authenticated OrgMesh gateway."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


UPSTREAM_COMMIT = "2dcbde772ce46687c5c220f4e1e4886bdfe91cc9"
BASE_PATH = "/presenton"
NEXT_ROOT = "servers/nextjs/"


def git_output(source: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), *arguments], text=True
    )


def replace_once(text: str, before: str, after: str, file: str) -> str:
    if text.count(before) != 1:
        raise RuntimeError(f"The pinned frontend patch does not match {file}.")
    return text.replace(before, after, 1)


def replace_function(text: str, name: str, body: str, file: str) -> str:
    pattern = rf"(?:export )?function {name}\([^\n]*\)[^\n]*\{{[\s\S]*?\n\}}"
    result, count = re.subn(pattern, lambda _: body, text, count=1)
    if count != 1:
        raise RuntimeError(f"The pinned frontend function {name} is missing in {file}.")
    return result


def prefix_public_assets(text: str, public_names: list[str]) -> str:
    alternatives = "|".join(re.escape(name) for name in public_names)
    # Directory entries require a slash, so Next navigation such as /dashboard stays unchanged.
    pattern = rf"([\"'`])/(?:{alternatives})"
    return re.sub(pattern, lambda match: match.group(0)[0] + BASE_PATH + match.group(0)[1:], text)


TRANSLATIONS = {
    "Rename presentation": "重命名演示文稿",
    "Presentation title": "演示文稿标题",
    "Save title": "保存标题",
    "Save · Enter": "保存 · Enter",
    "Cancel · Esc": "取消 · Esc",
    "Cancel editing title": "取消编辑标题",
    "Presentation": "演示文稿",
    "Export": "导出",
    "Exporting PPTX": "正在导出 PPTX",
    "Exporting PDF": "正在导出 PDF",
    "Your presentation is being exported. This may take a moment.": "正在导出演示文稿，请稍候。",
    "Export complete": "导出完成",
    "Your PPTX file has been downloaded.": "PPTX 文件已下载。",
    "Your PDF file has been downloaded.": "PDF 文件已下载。",
    "Export failed": "导出失败",
    "We are having trouble exporting your presentation. Please try again.": "无法导出演示文稿，请重试。",
    "Undo": "撤销",
    "Redo": "重做",
    "Present": "播放",
    "Keyboard shortcuts (?)": "快捷键（?）",
    "Keyboard shortcuts": "快捷键",
    "Element selection is on": "已开启元素选择",
    "Click a slide element to add it to AI chat": "点击幻灯片中的元素，将其添加到 AI 对话",
    "Select to edit": "选择元素进行编辑",
    "AI Assistant": "AI 助手",
    "Close AI Assistant": "关闭 AI 助手",
    "Chats": "对话",
    "New chat": "新对话",
    "What can I do": "今天需要我",
    "for your deck today?": "如何改进演示文稿？",
    "Rewrite for executives": "改写为管理层汇报",
    "Improve slide layout": "优化幻灯片布局",
    "Add data & citations": "添加数据与引用",
    "Create speaker notes": "生成演讲备注",
    "Make the deck consistent": "统一演示文稿风格",
    "Navigate with": "切换幻灯片：",
    "or the left thumbnails": "或点击左侧缩略图",
    "Dismiss navigation hint": "关闭导航提示",
    "Cancel": "取消",
    "Close": "关闭",
    "Save": "保存",
    "Saved": "已保存",
    "Saving...": "正在保存…",
    "Changes saved": "更改已保存",
    "Delete": "删除",
    "Duplicate": "复制",
    "Copy": "复制",
    "Paste": "粘贴",
    "Cut": "剪切",
    "Bring to front": "置于顶层",
    "Bring forward": "上移一层",
    "Send backward": "下移一层",
    "Send to back": "置于底层",
    "Font size": "字号",
    "Font family": "字体",
    "Text color": "文字颜色",
    "Bold": "加粗",
    "Italic": "斜体",
    "Underline": "下划线",
    "Strikethrough": "删除线",
    "Opacity": "不透明度",
    "No fonts": "没有可用字体",
    "Alignment is unavailable for list text": "列表文字不支持此对齐方式",
    "Image border radius": "图片圆角",
    "Border radius": "圆角",
    "Image opacity": "图片不透明度",
    "Close crop controls": "关闭裁剪工具",
    "Upload failed": "上传失败",
    "Image uploaded": "图片已上传",
    "The selected image was replaced.": "已替换所选图片。",
    "Please choose a valid image file.": "请选择有效的图片文件。",
    "Image files must be smaller than 5MB.": "图片文件必须小于 5MB。",
    "Add text": "添加文字",
    "Add image": "添加图片",
    "Add slide": "添加幻灯片",
    "Add Slides": "添加幻灯片",
    "Delete slide": "删除幻灯片",
    "Duplicate slide": "复制幻灯片",
    "Delete Slide": "删除幻灯片",
    "Duplicate Slide": "复制幻灯片",
    "Slide actions": "幻灯片操作",
    "Move Up": "上移",
    "Move Down": "下移",
    "Blank": "空白幻灯片",
    "Use Template": "使用模板",
    "More": "更多",
    "Group": "组合",
    "Ungroup": "取消组合",
    "Editor tools": "编辑工具",
    "Texts": "文字",
    "Charts": "图表",
    "Infographics": "信息图",
    "Tables": "表格",
    "Images": "图片",
    "Elements": "元素",
    "Search blocks": "搜索组件",
    "Create block": "创建组件",
    "Speaker notes": "演讲备注",
    "Failed to load presentation": "无法加载演示文稿",
    "The presentation could not be loaded. Please try again.": "演示文稿加载失败，请重试。",
    "Retry": "重试",
}


def translate_controls(text: str) -> str:
    for english, chinese in TRANSLATIONS.items():
        for quote in ('"', "'"):
            text = text.replace(f"{quote}{english}{quote}", f"{quote}{chinese}{quote}")
        pattern = rf">(\s*){re.escape(english)}(\s*)<"
        text = re.sub(pattern, lambda m: f">{m.group(1)}{chinese}{m.group(2)}<", text)
    return text


def prepare(source: Path) -> list[str]:
    if git_output(source, "rev-parse", "HEAD").strip() != UPSTREAM_COMMIT:
        raise RuntimeError("Use the pinned Presenton checkout before applying the frontend overlay.")

    names = git_output(source, "ls-tree", "-r", "--name-only", UPSTREAM_COMMIT, NEXT_ROOT).splitlines()
    public_root = source / NEXT_ROOT / "public"
    public_names = [
        entry.name + ("/" if entry.is_dir() else "")
        for entry in public_root.iterdir()
    ]
    changed: list[str] = []

    for git_path in names:
        relative = git_path.removeprefix(NEXT_ROOT)
        if Path(relative).suffix not in {".ts", ".tsx", ".css", ".mjs"}:
            continue
        if relative.startswith(("tests/", "cypress/")) and relative != "tests/backend-connectivity.test.mjs":
            continue
        original = git_output(source, "show", f"{UPSTREAM_COMMIT}:{git_path}")
        text = original

        if relative == "tests/backend-connectivity.test.mjs":
            text = replace_once(text, 'test("Next.js public font URLs are not rewritten as backend assets",', 'test("Next.js public font URLs use the embedded frontend prefix",', relative)
            text = replace_once(text, "assert.equal(connectivity.resolveBackendAssetUrl(fontUrl), fontUrl);", "assert.equal(connectivity.resolveBackendAssetUrl(fontUrl), `/presenton${fontUrl}`);", relative)
            text = replace_once(text, 'test("font URLs remain unchanged when normalizing a template response",', 'test("template font URLs use the embedded frontend prefix",', relative)
            text = replace_once(text, "assert.deepEqual(connectivity.normalizeBackendAssetUrls(response), response);", "assert.deepEqual(connectivity.normalizeBackendAssetUrls(response), {\n    fonts: { Poppins: `/presenton${fontUrl}` },\n  });", relative)

        if relative == "next.config.mjs":
            text = replace_once(text, "  reactStrictMode: false,", '  basePath: "/presenton",\n  reactStrictMode: false,', relative)
            text = replace_once(text, "unoptimized: isElectronBuild,", "unoptimized: true,", relative)

        if relative == "components/slide-editor/text/text-line-height.ts":
            text = replace_once(
                text,
                "const TEXT_AVERAGE_CHAR_EM = 0.52;",
                """const TEXT_AVERAGE_CHAR_EM = 0.52;

export function clampTextLineHeight(
  value: number | null | undefined,
  fallback = 1.15,
): number {
  const lineHeight = typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
  return Math.max(1.1, lineHeight);
}""",
                relative,
            )
            text = replace_once(
                text,
                """  return shouldApplyLineHeight({ text, width, fontSize, wrap })
    ? lineHeight ?? fallback
    : fallback;""",
                """  return clampTextLineHeight(
    shouldApplyLineHeight({ text, width, fontSize, wrap }) ? lineHeight : fallback,
    fallback,
  );""",
                relative,
            )

        if relative == "components/slide-editor/text/template-v2-text.ts":
            text = replace_once(
                text,
                'import { effectiveLineHeight } from "@/components/slide-editor/text/text-line-height";',
                'import { clampTextLineHeight, effectiveLineHeight } from "@/components/slide-editor/text/text-line-height";',
                relative,
            )
            text = replace_once(
                text,
                """    lineHeight:
      readNumber(font?.line_height) ??
      readNumber(font?.lineHeight) ??
      fallback.lineHeight,""",
                """    lineHeight: clampTextLineHeight(
      readNumber(font?.line_height) ?? readNumber(font?.lineHeight),
      fallback.lineHeight,
    ),""",
                relative,
            )

        if relative in {
            "components/slide-editor/text/StaticHtmlTextLayer.tsx",
            "components/slide-editor/text/TiptapInlineTextEditor.tsx",
        }:
            text = replace_once(
                text,
                '"use client";',
                '"use client";\n\nimport { clampTextLineHeight } from "@/components/slide-editor/text/text-line-height";',
                relative,
            )

        if relative == "components/slide-editor/text/StaticHtmlTextLayer.tsx":
            text = replace_once(text, "lineHeight: font.line_height ?? 1.15,", "lineHeight: clampTextLineHeight(font.line_height),", relative)
            text = replace_once(text, '          ...style,\n          display: run.display_mode ? "block" : "inline-block",', '          ...style,\n          lineHeight: "normal",\n          display: run.display_mode ? "block" : "inline-block",', relative)
            text = replace_once(text, "return (font.size ?? 18) * (font.line_height ?? 1.15);", "return (font.size ?? 18) * clampTextLineHeight(font.line_height);", relative)

        if relative == "components/slide-editor/text/TiptapInlineTextEditor.tsx":
            text = replace_once(text, "attrs.lineHeight != null ? `line-height:${attrs.lineHeight}` : null,", "attrs.lineHeight != null ? `line-height:${clampTextLineHeight(attrs.lineHeight)}` : null,", relative)
            text = replace_once(text, "return (font.size ?? baseFont.size ?? 18) * (font.line_height ?? 1.15);", "return (font.size ?? baseFont.size ?? 18) * clampTextLineHeight(font.line_height);", relative)

        if relative == "lib/template-v2-json-to-html.ts":
            text = 'import { clampTextLineHeight } from "@/components/slide-editor/text/text-line-height";\n' + text
            text = replace_once(text, "return `line-height:${cssNumber(lineHeight)};`;", "return `line-height:${cssNumber(clampTextLineHeight(lineHeight))};`;", relative)

        if relative == "utils/api.ts":
            text = 'import { stripPresentonBasePath, withPresentonBasePath } from "@/lib/orgmesh-paths";\n' + text
            text = replace_function(text, "getFastApiUrlFromQuery", "function getFastApiUrlFromQuery(): string | null {\n  return null;\n}", relative)
            text = replace_function(text, "shouldUseDirectFastApiOriginInBrowser", "function shouldUseDirectFastApiOriginInBrowser(): boolean {\n  return false;\n}", relative)
            text = replace_once(text, "  const normalizedPath = withLeadingSlash(path);\n\n  // Docker", "  const normalizedPath = stripPresentonBasePath(withLeadingSlash(path));\n\n  // Docker", relative)
            text = replace_once(text, "    return normalizedPath;\n  }\n\n  return `${getFastAPIUrl()}${normalizedPath}`;", "    return withPresentonBasePath(normalizedPath);\n  }\n\n  return `${getFastAPIUrl()}${normalizedPath}`;", relative)
            text = replace_once(text, "  const normalizedPath = withLeadingSlash(path);\n  const isFastApiEndpoint", "  const normalizedPath = stripPresentonBasePath(withLeadingSlash(path));\n  const isFastApiEndpoint", relative)
            text = replace_once(text, "  if (!isFastApiEndpoint) {\n    return normalizedPath;\n  }", "  if (!isFastApiEndpoint) {\n    return withPresentonBasePath(normalizedPath);\n  }", relative)
            text = replace_once(text, '  const normalized = rawPath.replace(/\\\\/g, "/");', '  const normalized = stripPresentonBasePath(rawPath.replace(/\\\\/g, "/"));', relative)
            text = replace_once(text, "  return trimmedPath;\n}\n\nexport type BackendAssetLike", '  return trimmedPath.startsWith("/vendor/")\n    ? withPresentonBasePath(trimmedPath)\n    : trimmedPath;\n}\n\nexport type BackendAssetLike', relative)
            text = replace_once(text, "  return hasBackendAssetPrefix(\n    toBackendServedPath(withLeadingSlash(normalizedPath))\n  );", '  return stripPresentonBasePath(normalizedPath).startsWith("/vendor/") || hasBackendAssetPrefix(\n    toBackendServedPath(withLeadingSlash(normalizedPath))\n  );', relative)

        if relative == "components/slide-editor/text/local-fonts.ts":
            text = 'import { resolveBackendAssetUrl } from "@/utils/api";\n' + text
            text = replace_once(text, "const normalizedSourceUrl = sourceUrl.trim();", "const normalizedSourceUrl = resolveBackendAssetUrl(sourceUrl.trim());", relative)

        # These modules execute in the browser. Internal FastAPI paths stay unprefixed.
        browser_module = relative.startswith(("components/", "store/")) or (
            relative.startswith("app/") and not relative.startswith("app/api/")
        ) or relative in {"utils/mixpanel.ts", "utils/storeHelpers.ts", "lib/svg-color.ts"}
        if browser_module:
            text = re.sub(r"([\"'`])/api/", lambda m: m.group(1) + BASE_PATH + "/api/", text)

        if relative != "utils/api.ts" and not relative.startswith(("app/api/", "tests/")):
            text = prefix_public_assets(text, public_names)

        if relative.startswith("components/slide-editor/") or "/presentation/" in relative:
            text = translate_controls(text)

        if relative == "app/(presentation-generator)/presentation/components/Chat.tsx":
            text = text.replace("`Slide ${currentSlide + 1}`", "`幻灯片 ${currentSlide + 1}`")

        if relative == "app/layout.tsx":
            text = text.replace('<html lang="en">', '<html lang="zh-CN">')
            text = text.replace('title: "Presenton - Open Source AI presentation generator",', 'title: "OrgMesh 演示文稿",')
            text = text.replace('import MixpanelInitializer from "./MixpanelInitializer";\n', "")
            text = text.replace("          <MixpanelInitializer>\n", "").replace("          </MixpanelInitializer>\n", "")

        if relative == "app/providers.tsx":
            text = text.replace("import ChatGptAuthRedirectHandler from './ChatGptAuthRedirectHandler';\n", "")
            text = text.replace("      <ChatGptAuthRedirectHandler />\n", "")

        if relative == "utils/mixpanel.ts":
            text = replace_function(text, "canUseMixpanel", "function canUseMixpanel(): boolean {\n  return false;\n}", relative)

        if relative == "app/(presentation-generator)/(dashboard)/layout.tsx":
            text = replace_once(text, '            <DashboardSidebar\n                showCommunity={isCommunityEnabled(process.env.PRESENTON_COMMUNITY_ENABLED)}\n                showTemplates={presentationGenerationMode !== "smart"}\n            />', "", relative)

        if relative == "app/(presentation-generator)/presentation/components/PresentationHeader.tsx":
            text = replace_once(text, '"use client";', '"use client";\nimport { withPresentonBasePath } from "@/lib/orgmesh-paths";', relative)
            text = replace_once(text, "    link.href = path;", "    link.href = withPresentonBasePath(path);", relative)
            text, count = re.subn(r'          <img\n            onClick=\{\(\) => \{\n              router.push\("/dashboard"\);\n            \}\}\n            src="/presenton/logo-with-bg.png"\n            alt=""\n            className="w-10 h-10 cursor-pointer object-contain"\n          />', "", text)
            if count != 1:
                raise RuntimeError("The pinned editor logo does not match.")
            text, count = re.subn(r'            <ToolTip content="Regenerate Presentation">[\s\S]*?            </ToolTip>\n            <Separator orientation="vertical" className="h-4" />', "", text, count=1)
            if count != 1:
                raise RuntimeError("The pinned regeneration control does not match.")
            text = re.sub(r"  const handleReGenerate = \(\) => \{[\s\S]*?(?=  const downloadLink)", "", text, count=1)
            text = re.sub(r"      <Dialog\n        open=\{isRegenerateConfirmOpen\}[\s\S]*?      </Dialog>\n", "", text, count=1)
            text = re.sub(r"import \{\n  Dialog,[\s\S]*?\} from \"@/components/ui/dialog\";\n", "", text, count=1)
            text = text.replace('  const [isRegenerateConfirmOpen, setIsRegenerateConfirmOpen] = useState(false);\n', "")
            text = text.replace('import { clearHistory } from "@/store/slices/undoRedoSlice";\n', "")
            for unused in ("RotateCcw", "AlertTriangle", "clearPresentationData"):
                text = text.replace(f"  {unused},\n", "")

        if relative == "app/api/export-presentation/route.ts":
            text = replace_once(text, 'return `/api/export-presentation/file?name=', 'return `/presenton/api/export-presentation/file?name=', relative)

        if relative == "lib/run-bundled-presentation-export.ts":
            text = 'import { getPresentonRenderBaseUrl } from "@/lib/orgmesh-paths";\n' + text
            text = replace_once(text, '  const nextjsUrl =\n    process.env.NEXT_PUBLIC_URL?.trim() || "http://127.0.0.1";', '  const nextjsUrl = getPresentonRenderBaseUrl(process.env.NEXT_PUBLIC_URL);', relative)
            text = replace_once(text, '  const fastapiUrl = process.env.NEXT_PUBLIC_FAST_API?.trim();', '  const fastapiUrl = undefined;', relative)

        if relative == "app/api/update-svg/route.ts":
            text = 'import { stripPresentonBasePath } from "@/lib/orgmesh-paths";\n' + text
            text = replace_once(text, 'pathname = decodeURIComponent(new URL(sourceUrl, requestUrl).pathname);', 'pathname = stripPresentonBasePath(decodeURIComponent(new URL(sourceUrl, requestUrl).pathname));', relative)

        if text != original:
            (source / git_path).write_text(text)
            changed.append(relative)

    overlay = Path(__file__).parent / "frontend"
    for entry in sorted(overlay.rglob("*")):
        if not entry.is_file():
            continue
        destination = source / NEXT_ROOT / entry.relative_to(overlay)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry.read_bytes())
        changed.append(str(entry.relative_to(overlay)))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pinned Presenton checkout")
    arguments = parser.parse_args()
    changed = prepare(arguments.source.resolve())
    print(f"Prepared {len(changed)} Presenton frontend files at {arguments.source.resolve() / NEXT_ROOT}")


if __name__ == "__main__":
    main()
