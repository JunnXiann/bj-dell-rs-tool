from pdf_craft import PDFPageExtractor, MarkDownWriter
import os


class CraftPdf:
    extractor = None

    def __init__(self):
        self.extractor = PDFPageExtractor(
            device="cpu",  # 如果希望使用 CUDA，请改为 device="cuda" 这样的格式。
            model_dir_path="models/deepseek-llm-7b-chat",  # AI 模型下载和安装的文件夹地址
        )

    def craft(self, title):
        markdown_path = f"output/contents/{title}.md"
        image_path = f"output/images/{title}"
        if not os.path.exists(f"{image_path}"):
            os.makedirs(f"{image_path}")

        with MarkDownWriter(markdown_path, f"../../{image_path}", "utf-8") as md:
            index = 1
            for block in self.extractor.extract(pdf=f"input/{title}.pdf"):
                md.write(block)
                print(f"index: {index}")
                index += 1


if __name__ == "__main__":
    pdf_craft = CraftPdf()
    title = "大乘起信论校释_10157709"
    pdf_craft.craft(title)
