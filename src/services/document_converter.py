# =============================================================================
# 文档转换：Word (.docx/.doc) -> Markdown
# =============================================================================

from __future__ import annotations

from pathlib import Path

from src.core.logging_config import get_logger

logger = get_logger(__name__)


def convert_word_to_markdown(file_path: Path | str) -> str:
    """
    将 Word 文档转换为 Markdown 文本。

    - .docx: 优先使用 mammoth；失败时回退 python-docx 纯文本抽取
    - .doc:  尝试 mammoth；若不支持则抛出明确错误
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    suffix = path.suffix.lower()
    if suffix not in {".doc", ".docx"}:
        raise ValueError(f"非 Word 文档，无法转换: {suffix}")

    # 优先 mammoth（保留标题/列表等结构）
    try:
        import mammoth

        with path.open("rb") as f:
            result = mammoth.convert_to_markdown(f)
        markdown = (result.value or "").strip()
        if result.messages:
            for msg in result.messages:
                logger.debug("mammoth 转换提示: %s", msg)
        if markdown:
            logger.info("Word->Markdown 成功(mammoth): %s，长度=%d", path.name, len(markdown))
            return markdown
        logger.warning("mammoth 输出为空，尝试 python-docx 回退: %s", path.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mammoth 转换失败，尝试回退: %s", exc)

    if suffix == ".doc":
        raise ValueError(
            "旧版 .doc 格式转换失败，请将文件另存为 .docx 后重新上传"
        )

    # python-docx 回退：按段落拼接为 Markdown
    try:
        import docx

        document = docx.Document(str(path))
        lines: list[str] = []
        for para in document.paragraphs:
            text = (para.text or "").strip()
            if not text:
                continue
            style_name = (para.style.name or "") if para.style else ""
            if style_name.startswith("Heading"):
                level = "".join(ch for ch in style_name if ch.isdigit()) or "1"
                lines.append(f"{'#' * int(level)} {text}")
            else:
                lines.append(text)
        markdown = "\n\n".join(lines).strip()
        if not markdown:
            raise ValueError("Word 文档无有效文本内容")
        logger.info(
            "Word->Markdown 成功(python-docx): %s，长度=%d",
            path.name,
            len(markdown),
        )
        return markdown
    except Exception as exc:  # noqa: BLE001
        logger.exception("Word 转换失败: %s", exc)
        raise ValueError(f"Word 文档转换为 Markdown 失败: {exc}") from exc


def ensure_markdown_file(
    source_path: Path,
    output_dir: Path,
    document_id: str,
) -> Path:
    """
    确保得到可索引的 Markdown 文件。

    - 若源文件已是 .md/.markdown/.txt：直接返回原路径（或复制）
    - 若是 Word：转换后写入 output_dir/{document_id}.md
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()

    if suffix in {".md", ".markdown", ".txt"}:
        return source_path

    if suffix in {".doc", ".docx"}:
        md_text = convert_word_to_markdown(source_path)
        target = output_dir / f"{document_id}.md"
        target.write_text(md_text, encoding="utf-8")
        logger.info("已生成 Markdown 文件: %s", target)
        return target

    raise ValueError(f"不支持的文件格式: {suffix}")